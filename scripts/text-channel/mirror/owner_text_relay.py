#!/usr/bin/env python3
"""owner_text_relay -- the single policy brain for every text that reaches the owner.

One module, one store, every door submits, one thing decides.  This module is
POLICY ONLY: it never transmits.  A door (textsend.py, the app sender, the
heartbeat, the ai-line) submits an intent, gets a verdict, and -- only when the
verdict is SEND -- transmits and then calls record_sent()/record_failed().

    store ......... /root/.owner-text/relay.db     (override: OWNER_TEXT_RELAY_DB)
    schema ........ created idempotently by connect(); WAL + busy_timeout=5000
    verdicts ...... SEND | DEDUPE | FLOOR | TOO_LONG | COALESCE | SUPPRESS
    policy ........ OWNER_TEXT_RELAY_MIN_GAP_MINUTES   (default 20)
                    OWNER_TEXT_RELAY_DUP_HOURS         (default 6)
                    OWNER_TEXT_RELAY_MAX_RETRIES       (default 3)
                    OWNER_TEXT_RELAY_COALESCE_MINUTES  (default 90)
                    OWNER_TEXT_RELAY_MAX_CHARS         (default 320)
                    OWNER_TEXT_RELAY_OFF               (kill switch; "1" => everything SEND)
    constants ..... DEDUPE_EXEMPT_SUBSYSTEMS           ({"security_alert_mms"})
                    REPLY_CLASS                        ("reply")

Importing this module does nothing: no store is touched, no output is printed.
The store (and its parent directory) is created by connect().

FAIL-SOFT IS THE CALLER'S JOB.  Every door MUST use exactly this two-line
pattern, so that a relay outage is logged and never silent:

    try:
        import owner_text_relay as relay; verdict = relay.submit(door="textsend", subsystem="cfo-ask", body=body)
    except Exception as exc:
        log(f"owner-text relay unavailable ({exc!r}); sending anyway"); verdict = {"verdict": "SEND", "reason": "relay-unavailable"}

Line 1 is the relay; if it raises for ANY reason, line 2 writes one log line
NAMING the failure and the caller proceeds to send.  `available()` exists for a
pre-flight check but is NOT a substitute for the try/except -- the store can
fail between the check and the submit.  A relay outage may degrade to "no
policy" but may never degrade to "no text" and never to "no log line".

GUARANTEES
  * Every submit() writes its attempt row, whatever the verdict -- including
    SUPPRESS.  Nothing the owner was not told disappears from the record.
  * The read-decide-write runs inside ONE `BEGIN IMMEDIATE` transaction, so two
    doors submitting the same body in the same second cannot both get SEND.
  * The dedupe key is sha256(normalise(body)).  Timestamps are NOT part of it.
  * An ask is never silently dropped: it ends `answered` or `expired`.

CALLER OBLIGATIONS (not enforceable from here)
  * After a SEND verdict, call record_sent() or record_failed().  A SEND whose
    outcome is never recorded stays `pending` and (inside the dup window) will
    hold a later identical submission as `dup-inflight`.
  * Pass a stable `ref` with opens_ask=True so the reply router can find the ask.

DEDUPE IS NOT APPLIED TO EVERYTHING, AND THAT IS DELIBERATE (2026-10-14)
  The duplicate rules (3 `dup-sent` and 3b `dup-inflight`) trade a MISS for a
  duplicate: they assume that two identical bodies are the same event.  For most
  traffic that is right, and it is the 18-books fix.  For a SAFETY-CRITICAL class
  it is exactly backwards -- a duplicate page costs the owner one extra buzz, a
  page he never receives costs him the picture of an intruder -- so the trade is
  refused in two independent ways:

    * `dedupe_disabled=True` skips rules 3 and 3b for ONE submission.  The caller
      says "I know this looks like the last one; it is not the same event."  The
      retry cap (rule 4) is NOT skipped: rule 3 is what stops a duplicate, rule 4
      is what stops a STORM, and a storm is still a way to lose him.
    * `dedupe_extra="<event id>"` is appended to the normalised body BEFORE
      hashing, so a caller with a real event identity (a snapshot id, a
      transaction id, an alert key+timestamp) makes two genuinely different
      events hash differently without weakening the key for anyone else.
    * `DEDUPE_EXEMPT_SUBSYSTEMS` (default `{"security_alert_mms"}`) exempts a whole
      subsystem WITHOUT the caller asking.  This is a deliberate asymmetry: the
      relay refuses to be the thing that loses a page, so the exemption is the
      DEFAULT for that class and a caller who forgets is still covered.  The price
      is that a genuinely duplicated page for that subsystem is sent twice, which
      is the cheap direction of the trade.

  Both of these are policies of LAST RESORT.  A caller that knows its event
  identity should pass `dedupe_extra` and keep the dedupe; the subsystem
  exemption exists only because "forgot to pass the snapshot id" must not be the
  failure mode of a security alert.

A REPLY IS NOT HELD BY THE FLOOR (2026-10-14)
  Rule 5 (FLOOR) exists because the owner said "text me, let's say once every 20
  minutes at most" -- but that is a rule about UNSOLICITED traffic.  A message
  that ANSWERS something he just said is solicited; he is in a conversation, and
  holding his answer for 20 minutes IS the silence he is complaining about.  So
  `class_hint == REPLY_CLASS` ("reply") is exempt from the floor alongside
  `urgency in {"urgent","critical"}`.  The floor is the only rule this exempts: a
  reply is still deduped, still retry-capped and still length-checked.  The
  constant is exported so every door spells the class the same way.

NO COALESCER EXISTS -- THE COALESCE RULE WAS WITHDRAWN (2026-10-14, int-c)
  A prior rule returned `verdict="COALESCE"` for `class_hint` in
  `{"reminder","digest","info"}` at normal urgency, with the detail sentence
  "batched into the next 90-min digest window, not sent now".  No digest window
  and no coalescer exist anywhere in the estate, so the rule could only refuse a
  message and the sentence that explained the refusal was false -- a silent-loss
  mechanism with a lying excuse attached.  The branch is deleted; control now
  falls through to `SEND`.  `"COALESCE"` stays in `VERDICTS` (and `status()`
  still counts it) ONLY so rows written before the rule was withdrawn remain
  readable; no code path can write it any more.

THE ONE CEILING LIVES HERE (2026-10-14, int-c)
  Measured on the relay's first real submission (attempt_id=1, 2026-10-14
  01:54:50Z): the app door delivered a 766-character `ask_owner` body because the
  relay had no length policy and the app's own fitter fits to the TRANSPORT
  budget (1600/800), not to the owner's one-text ceiling.  So:
    * `MAX_CHARS` (default 320, `OWNER_TEXT_RELAY_MAX_CHARS`) is the single
      ceiling, and `submit()` returns `TOO_LONG` for any body over it -- after the
      kill switch and BEFORE the duplicate rules, so a text that will never be
      sent does not burn a dedupe slot.  The attempt row is written like every
      other verdict.
    * `fit(body, limit=None)` is exported so a door can COMPLY instead of being
      refused: it cuts on a sentence, then a clause, then a word boundary (never
      mid-word when such a boundary exists in the window), appends the existing
      `TRUNCATION_MARKER` only when it actually truncated, and never returns more
      than the limit.
  A refusal is a lost message, so every wired door must call `fit()` BEFORE
  `submit()`; `TOO_LONG` is reachable only by a caller that skipped it.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timedelta, timezone

__all__ = [
    "VERDICTS", "DEFAULT_DB", "TRUNCATION_MARKER", "MAX_CHARS",
    "DEDUPE_EXEMPT_SUBSYSTEMS", "REPLY_CLASS",
    "connect", "submit", "record_sent", "record_failed",
    "record_ask", "open_asks", "answer_ask", "expire_asks", "record_answer",
    "status", "doctor", "available",
    "normalise", "body_hash", "policy", "policy_sources", "db_path", "fit",
]

DEFAULT_DB = "/root/.owner-text/relay.db"
VERDICTS = ("SEND", "DEDUPE", "FLOOR", "TOO_LONG", "COALESCE", "SUPPRESS")

#: The one owner-text ceiling.  The relay is the only component that sees every
#: door, so the ceiling belongs here.  320 is the estate's existing convention for
#: an owner text (`textsend.fit_owner_body`'s ceiling / `OWNER_TEXT_MAX_CHARS`),
#: env-overridable so a deployment can move it without a code change.  Evaluated
#: at import time, like the rest of this module's constants.
MAX_CHARS = int(os.environ.get("OWNER_TEXT_RELAY_MAX_CHARS", "320"))

#: The ceiling for a message to someone who is NOT the owner. The 320-char ceiling exists
#: because of how HE reads a text (his own words: "way too much information at once"), not
#: because of a transport limit -- so applying it to a family member or a vendor was a
#: category error that silently stranded a 377-char message he had asked us to send
#: (attempts 74/75, 2026-10-18: `verdict=SEND`, `reason=too-long`, no sid, never delivered).
#: Twilio's own limit is 1600; this is that limit, and `send_message` already truncates there.
THIRD_PARTY_MAX = int(os.environ.get("OWNER_TEXT_THIRD_PARTY_MAX", "1600"))

#: Who counts as the owner. A recipient is the owner if their last ten digits are in this set.
#: Without it the relay cannot know WHOSE ceiling applies, which is the whole point of the
#: `to_number` column: "who got this" is the question the ledger could not answer.
OWNER_NUMBERS = frozenset(
    n.strip() for n in os.environ.get(
        "OWNER_PHONE_NUMBERS", os.environ.get("OWNER_PHONE_NUMBER", "+18483897895")
    ).split(",") if n.strip()
)


def _last10(number: str) -> str:
    digits = "".join(ch for ch in str(number or "") if ch.isdigit())
    return digits[-10:]


def is_owner_number(number: str) -> bool:
    """True when this recipient is the owner (checked on the last ten digits)."""
    want = _last10(number)
    return bool(want) and any(_last10(n) == want for n in OWNER_NUMBERS)


def ceiling_for(to: str | None) -> int:
    """The length ceiling that applies to THIS recipient.

    The 320-char ceiling is about how the owner reads a text, so it belongs to him alone; any
    other recipient gets the transport limit. This is a rule about the RECIPIENT, and the relay
    holds no opinion about which application a message came from -- Family Chat is a separate
    app that does not belong in this component (owner, 2026-10-18).

    An empty `to` is treated as the owner, because every pre-existing caller omitted it and
    defaulted to him -- fail toward the tighter, already-documented rule rather than silently
    granting a third-party allowance to the one reader whose ceiling this is.
    """
    if not to or is_owner_number(to):
        return MAX_CHARS
    return THIRD_PARTY_MAX

#: RETIRED 2026-10-15.  This was the string appended to any owner body the relay
#: had to cut, and it made the OWNER do the follow-up work -- it asked him to ask
#: for the rest, which is the opposite of a message that stands on its own.  His
#: words that day: "why does it sometimes say context cuts short? I don't know.
#: It's not like a normal, human-like texting system."  Measured over 30 days
#: before the change: 19 rows carried it (11 distinct Twilio sids, 8 plausibly
#: delivered), every one of them because a door had already committed to a body
#: three to five times the ceiling.
#:
#: AND IT IS NOT SILENT.  The old design kept the reader informed at the cost of
#: handing him a task; simply deleting the marker would make a half-answer
#: indistinguishable from a whole one -- measured on the live line, a body of 543
#: characters was posted as 194 and one of 612 as 281, i.e. he read 36 % and 46 %
#: of two reminders with nothing to say so.  So the fact moves OUT of his message
#: and INTO `FIT_LOG`: `fit()` writes every cut (original -> posted, with the
#: caller's door) there, and the doors already log their own before/after
#: lengths.  The reader is not told; the record is not lost.
TRUNCATION_MARKER = ""
#: Where a cut is recorded now that it is no longer written into the body.
FIT_LOG = os.environ.get("OWNER_TEXT_FIT_LOG", "/root/.owner-text/fit.log")

SUPPRESSED_CLASS = "suppressed-class"
URGENT_URGENCIES = ("urgent", "critical")
#: WITHDRAWN 2026-10-14 (int-c).  This tuple used to feed a rule that returned
#: verdict COALESCE with the detail "batched into the next 90-min digest window".
#: No digest window and no coalescer exist anywhere in the estate, so the rule
#: could only refuse a message and its explanation was false.  The rule is gone
#: (control falls through to SEND); the tuple is retained only as the historical
#: vocabulary of the withdrawn rule.  No code path reads it -- verified before the
#: rule was deleted with `grep -n COALESCE_CLASSES /root/bin /opt/company`, which
#: returned exactly two hits, both in this file.
COALESCE_CLASSES = ("reminder", "digest", "info")

#: Subsystems for which this module REFUSES to apply its own duplicate rules, even
#: when the caller asks for nothing.  Measured 2026-10-14 (r3-app OPEN RISK): an
#: intrusion page is an MMS whose identity is the snapshot, not the caption, so two
#: genuinely different intruder pictures share one `sha256(normalised caption)` and
#: the second was DEDUPEd and never transmitted.  For a safety-critical class a
#: duplicate is cheap and a miss is not, so the dedupe is traded away here by
#: DEFAULT -- a caller who forgets cannot lose a page.  The retry cap (rule 4) still
#: applies, so a storm is still stopped.  Deliberate asymmetry; see the docstring.
DEDUPE_EXEMPT_SUBSYSTEMS = {"security_alert_mms"}

#: The one `class_hint` that exempts a submission from the FLOOR (rule 5), besides
#: `urgency in URGENT_URGENCIES`: a message that ANSWERS something the owner just
#: said is solicited, and holding it is the silence he is complaining about.
#: Exported so callers and other modules use the same literal.
REPLY_CLASS = "reply"

DELIVERED_STATUSES = ("sent", "delivered")
FAILED_STATUSES = ("failed", "undelivered")

_POLICY_ENV = (
    ("min_gap_minutes", "OWNER_TEXT_RELAY_MIN_GAP_MINUTES", 20.0),
    ("dup_hours", "OWNER_TEXT_RELAY_DUP_HOURS", 6.0),
    ("max_retries", "OWNER_TEXT_RELAY_MAX_RETRIES", 3.0),
    ("coalesce_minutes", "OWNER_TEXT_RELAY_COALESCE_MINUTES", 90.0),
)

_SIGNOFF_RE = re.compile(r"(?:^|\s)[\-\u2013\u2014]\s*daniel\.?\s*$", re.IGNORECASE)
_TRAILING_PUNCT_RE = re.compile(r"[\s\W_]+$", re.UNICODE)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS attempt (
    attempt_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    at             TEXT    NOT NULL,
    door           TEXT    NOT NULL,
    subsystem      TEXT    NOT NULL,
    body           TEXT    NOT NULL DEFAULT '',
    body_hash      TEXT    NOT NULL,
    reason         TEXT    NOT NULL DEFAULT '',
    urgency        TEXT    NOT NULL DEFAULT 'normal',
    class_hint     TEXT,
    ref            TEXT,
    topic          TEXT,
    opens_ask      INTEGER NOT NULL DEFAULT 0,
    verdict        TEXT    NOT NULL,
    verdict_reason TEXT    NOT NULL,
    detail         TEXT    NOT NULL DEFAULT '',
    holds          TEXT    NOT NULL DEFAULT '[]',
    status         TEXT    NOT NULL DEFAULT 'pending',
    sid            TEXT    NOT NULL DEFAULT '',
    sent_at        TEXT,
    failed_at      TEXT,
    error          TEXT    NOT NULL DEFAULT '',
    to_number      TEXT    NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_attempt_hash    ON attempt(body_hash, at);
CREATE INDEX IF NOT EXISTS idx_attempt_status  ON attempt(status, sent_at);
CREATE INDEX IF NOT EXISTS idx_attempt_at      ON attempt(at);
CREATE INDEX IF NOT EXISTS idx_attempt_verdict ON attempt(verdict, at);

CREATE TABLE IF NOT EXISTS ask (
    ask_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    ref         TEXT    NOT NULL UNIQUE,
    subsystem   TEXT    NOT NULL,
    topic       TEXT    NOT NULL DEFAULT '',
    body        TEXT    NOT NULL DEFAULT '',
    asked_at    TEXT    NOT NULL,
    ttl_hours   REAL    NOT NULL DEFAULT 72.0,
    expires_at  TEXT    NOT NULL,
    state       TEXT    NOT NULL DEFAULT 'open',
    answered_at TEXT,
    answered_by TEXT,
    answer      TEXT,
    attempt_id  INTEGER
);
CREATE INDEX IF NOT EXISTS idx_ask_state ON ask(state, asked_at);
"""


# --------------------------------------------------------------------------
# time helpers -- every timestamp in this store is UTC ISO-8601, fixed width,
# so string comparison is chronological comparison.
# --------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _parse(ts):
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None


def _ago(seconds) -> str:
    s = max(0.0, float(seconds))
    if s < 90:
        return "%d s" % int(round(s))
    if s < 5400:
        return "%d min" % int(round(s / 60.0))
    if s < 172800:
        return "%.1f h" % (s / 3600.0)
    return "%.1f d" % (s / 86400.0)


def _writable_ancestor(path):
    """Nearest existing ancestor directory of `path` -- the one that has to be
    writable for connect() to create the store."""
    d = os.path.dirname(os.path.abspath(path))
    while d and not os.path.isdir(d):
        up = os.path.dirname(d)
        if up == d:
            break
        d = up
    return d if os.path.isdir(d) else None


# --------------------------------------------------------------------------
# normalisation + hash
# --------------------------------------------------------------------------

def normalise(body: str) -> str:
    """The one definition of "the same message".

    lowercase; drop the truncation marker; collapse whitespace runs to one
    space; strip a trailing "- Daniel" / "-Daniel" / "- Daniel." sign-off;
    strip trailing punctuation.  No timestamp is anywhere in here.
    """
    s = "" if body is None else str(body)
    s = s.lower()
    s = s.replace(TRUNCATION_MARKER, " ")
    s = re.sub(r"\s+", " ", s).strip()
    previous = None
    while previous != s:                      # marker may expose a sign-off
        previous = s
        s = _SIGNOFF_RE.sub("", s).strip()
    s = _TRAILING_PUNCT_RE.sub("", s)
    return s.strip()


def body_hash(body: str) -> str:
    """sha256 hex of normalise(body).  No timestamp, ever."""
    return hashlib.sha256(normalise(body).encode("utf-8")).hexdigest()


def policy_hash(body: str, dedupe_extra: str | None = None) -> str:
    """The hash the duplicate rules compare on.

    Identical to `body_hash(body)` when `dedupe_extra` is empty -- that is the
    whole point, no existing caller's key moves.  With a non-empty
    `dedupe_extra` the caller's own event identity is appended to the NORMALISED
    body before hashing, so two events that read the same but carry different
    identities (a snapshot id, a transaction id, `key+timestamp`) are two
    different keys, while two submissions of the SAME event with the same
    identity still dedupe against each other.

    The separator is a newline: `normalise()` collapses every whitespace run and
    strips the ends, so its output can never contain one -- the extra can
    therefore never be confused with the tail of the body.
    """
    material = normalise(body)
    if dedupe_extra is not None and str(dedupe_extra).strip() != "":
        material = material + "\n" + str(dedupe_extra).strip()
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------
# fit -- make a body comply with the one ceiling instead of being refused
# --------------------------------------------------------------------------

def _cut_at_boundary(window: str) -> str:
    """The largest honest cut of `window`: sentence, then clause, then word.

    The discipline is `app/owner_text.fit_for_one_text`'s (read 2026-10-14):
    a `.`/`?`/`!` only terminates a sentence when a space or the end of the
    window follows it (so the dot in `ezabz68@gmail.` is not a boundary), and a
    sentence cut must land in the second half of the window so a short message
    is not thrown away for one early full stop.  Then a clause break, then the
    last space.  Returns "" when the window has no boundary at all (one
    unbroken token); the caller decides what to do with that.
    """
    half = len(window) // 2
    best = None
    for end in (".", "?", "!", "\n"):
        at = window.rfind(end)
        if at <= 0:
            continue
        after = window[at + 1: at + 2]
        if end != "\n" and after not in ("", " "):
            continue
        if at < half:
            continue
        if best is None or at > best:
            best = at
    if best is not None:
        return window[: best + 1].rstrip(" -\u2014;:,")
    for end in (" - ", " \u2014 ", "; ", ", "):
        at = window.rfind(end)
        if at >= half:
            cut = window[:at].rstrip(" -\u2014;:,")
            if cut:
                return cut
    at = window.rfind(" ")
    if at > 0:
        return window[:at].rstrip(" -\u2014;:,")
    return ""


def _log_fit(original: str, posted: str, limit: int) -> None:
    """Record a cut that is no longer written into the owner's message.

    BEST-EFFORT BY DESIGN.  `fit()` sits on the only path his phone depends on,
    so a failure to write this line must never affect the text.  A missing line
    is a lost diagnostic; a raised exception here would be a lost message.
    """
    try:
        os.makedirs(os.path.dirname(FIT_LOG), exist_ok=True)
        with open(FIT_LOG, "a", encoding="utf-8") as fh:
            fh.write(
                "%s limit=%d %d->%d %r\n"
                % (_now().strftime("%Y-%m-%dT%H:%M:%SZ"), limit, len(original), len(posted), posted[:80])
            )
    except Exception:  # noqa: BLE001 - never let the record break the message
        pass


def fit(body: str, limit: int | None = None) -> str:
    """Return `body` cut to at most `limit` chars (default `MAX_CHARS`).

    THE POINT IS THAT A DOOR COMPLIES RATHER THAN IS REFUSED.  `submit()`
    returns `TOO_LONG` for an over-ceiling body; a refusal is a lost message, so
    every door fits first.  This is the helper they fit with, and the interface
    is frozen: `fit(body, limit=None) -> str`.

    The cut lands on a sentence boundary, then a clause boundary, then a word
    boundary (never mid-word when one of those exists in the window), reusing
    `_cut_at_boundary`'s discipline.  Nothing is appended: `TRUNCATION_MARKER`
    was RETIRED 2026-10-15 (see its definition) because it asked the owner for
    the rest, and `_log_fit` records the cut instead.  The result is NEVER
    longer than `limit`.  A body that already fits is returned byte-for-byte
    unchanged (no strip, no marker), so `fit(x) == x` for `len(x) <= limit`.

    Why this is written here and not imported: `textsend.fit_owner_body` is a
    sibling module but a `/root/bin` script whose import pulls in textstore,
    sms_inbox and owner_flood_guard and whose fit does not put the marker in the
    body (it returns a separate detail), and `app.owner_text.fit_for_one_text`
    lives in the app, which imports THIS module -- importing it here would be a
    package-level cycle and would make the policy-only relay depend on the app.
    Neither is importable cleanly, so the boundary discipline is re-implemented
    here, deliberately, with the same rules.
    """
    text = "" if body is None else str(body)
    try:
        limit_i = MAX_CHARS if limit is None else int(limit)
    except (TypeError, ValueError):
        limit_i = MAX_CHARS
    if limit_i <= 0:
        return ""
    if len(text) <= limit_i:
        return text
    marker = TRUNCATION_MARKER
    sep = " " if marker else ""
    room = limit_i - len(marker) - len(sep)
    if room <= 0:
        # The marker alone cannot fit (a caller asked for less than one marker):
        # the only cut that honours the limit is a hard trim with no marker.
        posted = "" if marker else text[:limit_i].rstrip()
        _log_fit(text, posted, limit_i)
        return posted
    cut = _cut_at_boundary(text[:room])
    if not cut:
        # One unbroken token: no sentence, clause or word boundary exists, so
        # the only cut that is never mid-word is the hard trim of the window.
        posted = text[:room].rstrip()
        _log_fit(text, posted, limit_i)
        return posted
    posted = (cut + sep + marker) if marker else cut
    _log_fit(text, posted, limit_i)
    return posted


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
# STANDING RULES -- what the owner has told us never to send again
# --------------------------------------------------------------------------
#
# The defect this replaces, measured 2026-10-15. He banned the daily digest twice in two
# days, in words:
#
#   2026-10-14T00:33:10Z  "This is a good example of a text that's useless. I have no idea
#                          what it means, it's too much information, and it's weird."
#   2026-10-14T14:18:21Z  "I already told you these random briefs seem pointless. I need one
#                          item at a time, ... not some random text that says 36 items, 30
#                          urgent, or something like that."
#
# The system acknowledged the second one -- "Saving that as a standing rule so it survives
# every session" -- and sent the same shape again 24 hours later (relay attempt 29, sid
# SM433eb01717ad795a7523621ad0f289b9). Two independent reasons, and neither was "nobody
# cared":
#
#   * `app/services/owner_notifications.py:122` matches briefings with
#     `reason.startswith("owner_briefing")`, and the digest's reason was
#     `owner_attention_digest` -- so the durable off-switch never applied to it; and
#   * `owner_text_suppression` matched its `topic` as a lowercase SUBSTRING of
#     (reason + body), and the single row it held all-time was keyed on his own complaint
#     sentence. A sentence can never appear in a later body. The mechanism was real and
#     structurally inert.
#
# So: the rule lives HERE, on the one path every door must pass, keyed on the CLASS THE
# PRODUCER NAMES. A class the producer can spell is a class that can be matched.
STANDING_RULES = os.environ.get(
    "OWNER_TEXT_STANDING_RULES", "/root/.owner-text/standing-rules.json")


def standing_rule_mutes(*classes: str | None) -> str:
    """The reason a standing rule closes one of `classes`, or "" for allowed.

    ALLOWS on every failure, deliberately. A missing, truncated or unreadable rules file
    must never be the reason a message he is owed goes unsent -- that is the exact trade
    `L3791` refuses. It says so on stderr rather than passing quietly, because a silent
    allow is indistinguishable from a rule that was read and did not match.
    """
    try:
        with open(STANDING_RULES, encoding="utf-8") as fh:
            rules = json.load(fh) or {}
    except FileNotFoundError:
        return ""
    except Exception as exc:  # noqa: BLE001 - allow, and never silently
        print("owner-text relay: standing rules at %s unreadable (%r); allowing"
              % (STANDING_RULES, exc), file=sys.stderr)
        return ""
    table = rules.get("classes") or {}
    if not isinstance(table, dict):
        return ""
    for cls in classes:
        name = str(cls or "").strip()
        if not name:
            continue
        entry = table.get(name) or {}
        if isinstance(entry, dict) and entry.get("allow") is False:
            return str(entry.get("why") or "closed by a standing rule")
    return ""


# --------------------------------------------------------------------------
# THE FRONT DESK -- one item in, one message out
# --------------------------------------------------------------------------
#
# Every door used to write its own body, and the result is the thing the owner described:
# "it's repetitive", "36 items, 18 urgent", "I need one item at a time". Sixteen length
# ceilings guarded one channel and nothing owned the WORDS.
#
# `compose()` is that owner, and it lives here rather than in any one producer because the
# relay is already the only component every door passes through. A door hands it an ITEM --
# a dict, not a paragraph -- and gets back one message.
#
# The shape of an item:
#   title          required. For a decision, the question as it would be asked. For a
#                  notice, the fact. A queue's whole finding is acceptable; it is cut.
#   action         optional. What we recommend, or what he must do. `recommendation` and
#                  `blocks` are accepted as aliases because that is what the producers
#                  already call them.
#   source, tier, severity, ref   optional metadata, used for nothing but the record.
#
# What it guarantees, all of them measured defects:
#   * ONE item. Never a count, never a list.
#   * It fits `limit` by CONSTRUCTION, cut at a sentence then a clause boundary -- so the
#     reader never sees a fragment, and never sees the retired
#     "[cut short - ask me to continue]" marker, which asked HIM for the rest.
#   * No machine shapes: a count-and-urgency head, a filesystem path, a bracket status.
#     `FORBIDDEN_IN_ITEM` is checked on the composed body, not on the input.
#   * A subject with no boundary long enough to be a fragment is DROPPED rather than
#     truncated: `_lede` returns "" rather than ending a sentence in "the".
FORBIDDEN_IN_ITEM = (
    "cut short",
    "ask me to continue",
    "data/owner-attention",
    "full: ",
    "items, ",
)
_ITEM_ACTION_KEYS = ("action", "recommendation", "blocks")


def _item_text(value, limit: int) -> str:
    """One sentence, whitespace-collapsed, cut at a real boundary; "" if none exists."""
    text = " ".join(str(value or "").split())
    if not text:
        return ""

    def close_parens(cut: str) -> str:
        # A fragment that opened a parenthesis it did not close reads as a typo:
        # measured `Deep Infra has been dead since 2026-10-02 (card declined`. Applies to
        # the UNTRUNCATED case too, because the unclosed bracket is in the producer's text.
        if cut.count("(") > cut.count(")"):
            cut = cut[: cut.rfind("(")].strip(" ,;:-\u2014")
        return cut

    if len(text) <= limit:
        return close_parens(text)
    window = text[:limit]
    for sep, keep in ((": ", False), (" - ", False), ("; ", False), (", ", False),
                      ("\u2014 ", False), ("? ", True), ("! ", True), (". ", True)):
        at = window.rfind(sep)
        if at > limit // 3:
            return close_parens((window[: at + 1] if keep else window[:at]).strip(" ,;:-\u2014"))
    at = window.rfind(" ")
    if at > limit // 3:
        return close_parens(window[:at].strip(" ,;:-\u2014"))
    return ""


def compose(item: dict, *, limit: int | None = None) -> str:
    """ONE message for ONE item, at most `limit` chars (default MAX_CHARS). "" if none."""
    if not isinstance(item, dict):
        item = {"title": str(item or "")}
    limit_i = int(limit) if limit else MAX_CHARS
    if limit_i <= 0:
        return ""
    subject = _item_text(item.get("title"), max(40, limit_i // 3))
    action = ""
    for key in _ITEM_ACTION_KEYS:
        action = _item_text(item.get(key), limit_i - 40)
        if action:
            break
    if subject and action and len("%s \u2014 %s" % (subject, action)) <= limit_i:
        body = "%s \u2014 %s" % (subject, action)
    elif action and (not subject or len(subject) >= limit_i // 3):
        # The subject would have to be cut to make room, and a cut subject is the mush.
        # The action is the half he can act on, so it is the half that goes.
        body = action
    else:
        body = subject or action or _item_text(item.get("detail"), limit_i)
    body = body[:limit_i].strip()
    for bad in FORBIDDEN_IN_ITEM:
        if bad.lower() in body.lower():
            print("owner-text relay: compose refused a body containing %r" % bad,
                  file=sys.stderr)
            return ""
    return body


def submit_item(door: str, subsystem: str, item: dict, *, ref: str | None = None,
                urgency: str = "normal", topic: str | None = None,
                ttl_hours: float = 72.0, conn=None) -> dict:
    """Compose ONE item and ask the gate about it -- the whole front desk in one call.

    Returns the `submit()` verdict plus `body` (what `compose` produced), so a caller that
    must transmit can post exactly those bytes: the judged body and the posted body are the
    same object, which is the `L3790` property.
    """
    body = compose(item)
    out = {"body": body, "verdict": "SUPPRESS", "reason": "empty-compose", "attempt_id": None}
    if not body:
        out["detail"] = "SUPPRESS: nothing to say -- the item composed to an empty body"
        return out
    opens_ask = bool(item.get("opens_ask"))
    got = submit(door=door, subsystem=subsystem, body=body, reason=str(item.get("reason") or ""),
                 urgency=urgency, ref=ref, topic=topic or item.get("topic"),
                 opens_ask=opens_ask, conn=conn)
    out.update(got)
    out["body"] = body
    if opens_ask and ref and got.get("verdict") == "SEND":
        try:
            out["ask"] = record_ask(ref, subsystem, topic or str(item.get("title") or ""),
                                    body, ttl_hours=ttl_hours, conn=conn)
        except Exception as exc:  # noqa: BLE001 - the record must not cost the message
            print("owner-text relay: ask %s not recorded (%r)" % (ref, exc), file=sys.stderr)
    return out


# policy values
# --------------------------------------------------------------------------

def policy() -> dict:
    """Effective policy values (floats / bool), for the decision and for logs."""
    out = {}
    for key, env, default in _POLICY_ENV:
        raw = os.environ.get(env)
        if raw is None or raw.strip() == "":
            out[key] = default
        else:
            try:
                out[key] = float(raw)
            except ValueError:
                out[key] = default
    out["kill_switch"] = os.environ.get("OWNER_TEXT_RELAY_OFF") == "1"
    return out


def policy_sources() -> list:
    """[{name, env, value, source}] with source in env | env-invalid | default."""
    rows = []
    for key, env, default in _POLICY_ENV:
        raw = os.environ.get(env)
        if raw is None or raw.strip() == "":
            rows.append({"name": key, "env": env, "value": default, "source": "default"})
            continue
        try:
            value = float(raw)
            source = "env"
        except ValueError:
            value = default
            source = "env-invalid"
        rows.append({"name": key, "env": env, "value": value, "source": source})
    raw_off = os.environ.get("OWNER_TEXT_RELAY_OFF")
    rows.append({
        "name": "kill_switch",
        "env": "OWNER_TEXT_RELAY_OFF",
        "value": raw_off == "1",
        "source": "default" if raw_off is None else "env",
    })
    return rows


# --------------------------------------------------------------------------
# store
# --------------------------------------------------------------------------

def db_path(path=None) -> str:
    if path:
        return path
    return os.environ.get("OWNER_TEXT_RELAY_DB") or DEFAULT_DB


def connect(path=None) -> sqlite3.Connection:
    """Open (creating if needed) the relay store.  WAL, busy_timeout=5000.

    Creates the parent directory and the schema idempotently.  Returns a
    connection in autocommit mode (isolation_level=None) so that callers do
    their own `BEGIN IMMEDIATE`; the module's own writers always do.
    """
    p = db_path(path)
    parent = os.path.dirname(os.path.abspath(p))
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(p, timeout=5.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA journal_mode=WAL")
    _ensure_schema(conn)
    return conn


def _ensure_schema(conn) -> None:
    row = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name IN ('attempt','ask')"
    ).fetchone()
    if row[0] != 2:
        conn.executescript(SCHEMA_SQL)
    _ensure_columns(conn)


#: Additive columns this file needs but an older store does not have. ALTER TABLE ADD COLUMN
#: is safe on SQLite and does not rewrite the table; every entry is idempotent.
_ADDED_COLUMNS = (
    ("attempt", "to_number", "TEXT NOT NULL DEFAULT ''"),
)


def _ensure_columns(conn) -> None:
    """Migrate an existing store forward without touching a row.

    A relay that refuses to run because its store predates a column is a relay that drops
    every message it is handed, so this runs on every connect and is silent when there is
    nothing to do.
    """
    for table, column, decl in _ADDED_COLUMNS:
        try:
            cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        except sqlite3.Error:
            continue
        if not cols or column in cols:
            continue
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
            conn.commit()
        except sqlite3.Error:
            pass


class _Conn:
    """Borrow the caller's connection, or own a fresh one for this call."""

    __slots__ = ("conn", "owned")

    def __init__(self, conn=None, path=None):
        self.owned = conn is None
        self.conn = connect(path) if self.owned else conn

    def close(self):
        if self.owned and self.conn is not None:
            self.conn.close()


# --------------------------------------------------------------------------
# submit
# --------------------------------------------------------------------------

def submit(door: str, subsystem: str, body: str, *, reason: str = "",
           urgency: str = "normal", class_hint: str | None = None,
           ref: str | None = None, topic: str | None = None,
           opens_ask: bool = False, dedupe_disabled: bool = False,
           dedupe_extra: str | None = None, to: str = "", conn=None) -> dict:
    """Decide what (if anything) may be sent, and record the decision.

    Returns {"verdict", "reason", "attempt_id", "detail", "holds"} plus a few
    additive keys (body_hash, at, ask_ref).  Never raises for a policy reason;
    it raises only if the store cannot be opened (callers fail soft).

    `holds` is a list of attempt_id ints -- the rows whose existence produced
    the verdict (empty for SEND).

    DEDUPE OVERRIDES (both keyword-only and defaulted, so no existing caller
    changes shape):

      `dedupe_extra`  appended to the NORMALISED body before hashing (see
                      `policy_hash`).  Use it whenever the caller holds a real
                      event identity -- a snapshot id, a transaction id, an alert
                      key + timestamp -- so two genuinely different events that
                      read the same do not collide, while repeated submissions of
                      ONE event still dedupe.  A caller with such an identity
                      should use THIS and keep the dedupe, in preference to the
                      blunt instrument below.

      `dedupe_disabled=True`  skips rules 3 (`dup-sent`) and 3b (`dup-inflight`)
                      for this submission and NOTHING ELSE.  The retry cap (rule
                      4), the floor (rule 5), coalesce (rule 6) and the class mute
                      (rule 2) all still apply, so a storm is still stopped -- the
                      justification is per-CLASS, not per-caller: for a
                      safety-critical class a duplicate is cheap and a miss is
                      not, so the dedupe is traded away and only the retry cap
                      remains to stop a storm.  It is the caller's assertion "I
                      know this looks like the last one; it is not the same
                      event", and an assertion can be wrong.

    And one exemption the caller does NOT have to ask for:
    `DEDUPE_EXEMPT_SUBSYSTEMS` (`{"security_alert_mms"}`) skips rules 3 and 3b on
    its own.  This is a DELIBERATE ASYMMETRY: for that class the relay refuses to
    be the thing that loses a page, so the exemption is the default and a caller
    who forgets is still covered.  The cost is that a genuinely duplicated page in
    that subsystem IS sent twice -- the cheap direction of the trade.
    """
    body = "" if body is None else str(body)
    door = "" if door is None else str(door)
    subsystem = "" if subsystem is None else str(subsystem)
    to = "" if to is None else str(to).strip()
    urgency = (urgency or "normal").strip().lower() or "normal"
    if isinstance(class_hint, str):
        class_hint = class_hint.strip() or None
    elif class_hint is not None:
        class_hint = str(class_hint)

    ceiling = ceiling_for(to)

    # The duplicate rules are skipped when the caller asks (dedupe_disabled) OR when
    # the subsystem is safety-critical (DEDUPE_EXEMPT_SUBSYSTEMS) -- the second so a
    # caller who forgets cannot lose a page.  The hash is computed with the caller's
    # event identity when there is one, which distinguishes events without asking for
    # the blanket exemption.
    dedupe_exempt = subsystem in DEDUPE_EXEMPT_SUBSYSTEMS
    dedupe_skipped = bool(dedupe_disabled) or dedupe_exempt
    h = policy_hash(body, dedupe_extra)
    owns = _Conn(conn)
    c = owns.conn
    verdict = reason_code = None
    detail_t = None
    holds: list = []
    try:
        c.execute("BEGIN IMMEDIATE")
        try:
            now = _now()
            now_s = _iso(now)
            pol = policy()
            gap_min = float(pol["min_gap_minutes"])
            dup_hours = float(pol["dup_hours"])
            max_retries = int(pol["max_retries"])
            coalesce_min = float(pol["coalesce_minutes"])

            if pol["kill_switch"]:
                verdict, reason_code = "SEND", "kill-switch"
                detail_t = ("SEND: kill switch OWNER_TEXT_RELAY_OFF=1 is set, "
                            "policy bypassed (attempt {aid})")

            elif class_hint == SUPPRESSED_CLASS:
                verdict, reason_code = "SUPPRESS", "class"
                detail_t = ("SUPPRESS: class_hint 'suppressed-class' is muted by "
                            "policy, nothing sent (attempt {aid})")

            # Rule 1c, a STANDING RULE the owner gave (added 2026-10-15).
            #
            # He bans things in words -- "I already told you these random briefs seem
            # pointless. I need one item at a time" -- and until today the only store that
            # recorded it was `owner_text_suppression`, whose `topic` was matched as a
            # SUBSTRING of (reason + body). The single row it held all-time was keyed on his
            # own complaint sentence, so it could never match anything and no instruction he
            # ever gave had any effect on this channel.
            #
            # So the rule lives HERE, next to the other mutes, keyed on the CLASS a producer
            # names rather than on a quotation of the complaint. It is read on every submit,
            # so closing a class takes effect without a deploy. A file that is missing or
            # unreadable ALLOWS -- it must never be the reason a message he is owed goes
            # unsent -- and says so on stderr, because a silent allow looks identical to a
            # rule that passed.
            elif (muted := standing_rule_mutes(subsystem, class_hint)):
                verdict, reason_code = "SUPPRESS", "standing-rule"
                detail_t = ("SUPPRESS: a standing rule closes the %r class - %s "
                            "(attempt {aid})" % (subsystem, muted))

            # Rule 2b, the ceiling.  Evaluated AFTER the kill switch and BEFORE the
            # duplicate rules: a text that will never be sent must not burn a dedupe
            # slot.  A door that fits first (relay.fit) can never hit this; a refusal
            # here is the honest record of a caller that skipped the fit.
            elif len(body) > ceiling:
                # OVER THE CEILING IS RECORDED, NOT REFUSED -- deliberately.
                #
                # Why it does not block (manager, 2026-10-14). `TOO_LONG` was written to
                # refuse, on the theory that a door which fits its own body can never
                # reach it. Measured the same evening: it CAN, and it did.
                # `textsend.send()` posts its transport-fitted body (up to SOFT_LIMIT
                # 930) while `_relay_gate` handed the relay the RAW body, so every owner
                # text between 321 and 930 chars would have been refused -- a message a
                # door had already committed to, silently dropped. That is the exact
                # failure this relay was built to remove, so the ceiling may not be a
                # tripwire that only a perfect fleet can satisfy.
                #
                # So: measure it, record it, make it visible (`status()` counts
                # `too-long`), and let each DOOR enforce it by fitting. The app door
                # calls `fit()` before it submits; `textsend` reports the bytes it will
                # actually post. Nothing is lost and nothing is hidden.
                #
                # 2026-10-18: the ceiling is now `ceiling_for(to)`. The 320-char rule is
                # about HIS reading, so a third-party recipient gets Twilio's 1600. Before
                # this, a 377-char message he asked us to send to a family member was
                # recorded SEND/too-long and then stranded by the owner gate for nine
                # minutes of owner rate floor (attempts 74/75, sms_log 4280/4281).
                verdict, reason_code = "SEND", "too-long"
                detail_t = ("recorded: the body is %d chars, over the %d-char ceiling for "
                            "%s -- SENT anyway, because refusing here "
                            "would drop a message a door already committed to; that door "
                            "should have called fit() first (attempt {aid})"
                            % (len(body), ceiling,
                               "the owner" if ceiling == MAX_CHARS else "another recipient"))

            else:
                dup_cut = _iso(now - timedelta(hours=dup_hours))
                # Rules 3 and 3b are the DEDUPE pair and are the only two rules that
                # `dedupe_disabled` / DEDUPE_EXEMPT_SUBSYSTEMS can switch off. Everything
                # below them (the retry cap, the floor, coalesce) runs either way: a
                # duplicate is cheap, a STORM is not.
                held_by_dedupe = False
                if not dedupe_skipped:
                    dup = c.execute(
                        "SELECT attempt_id, status, COALESCE(sent_at, at) AS ts FROM attempt "
                        "WHERE body_hash=? AND status IN ('sent','delivered') "
                        "AND COALESCE(sent_at, at) >= ? "
                        "ORDER BY COALESCE(sent_at, at) DESC LIMIT 5",
                        (h, dup_cut),
                    ).fetchall()
                    if dup:
                        first = dup[0]
                        when = _parse(first["ts"]) or now
                        holds = [int(r["attempt_id"]) for r in dup]
                        verdict, reason_code = "DEDUPE", "dup-sent"
                        detail_t = ("DEDUPE: identical text already delivered %s ago "
                                    "(attempt %d) (attempt {aid})" % (_ago((now - when).total_seconds()),
                                                                     int(first["attempt_id"])))
                        held_by_dedupe = True
                    else:
                        # Only a submission that was CLEARED to send can be "in flight";
                        # rows held by another rule were never transmitted and must not
                        # mask the retry cap below.
                        inflight = c.execute(
                            "SELECT attempt_id, at FROM attempt WHERE body_hash=? AND status='pending' "
                            "AND verdict='SEND' AND at >= ? ORDER BY at DESC LIMIT 5",
                            (h, dup_cut),
                        ).fetchall()
                        if inflight:
                            first = inflight[0]
                            when = _parse(first["at"]) or now
                            holds = [int(r["attempt_id"]) for r in inflight]
                            verdict, reason_code = "DEDUPE", "dup-inflight"
                            detail_t = ("DEDUPE: an identical submission is already in flight "
                                        "(%s ago, attempt %d); not sending it twice (attempt {aid})"
                                        % (_ago((now - when).total_seconds()),
                                           int(first["attempt_id"])))
                            held_by_dedupe = True
                if not held_by_dedupe:
                    # Only attempts the relay CLEARED to send can be retries; a
                    # row held by another rule was never transmitted.
                    prev = c.execute(
                        "SELECT COUNT(*) AS n, "
                        "SUM(CASE WHEN status IN ('failed','undelivered') THEN 1 ELSE 0 END) AS f "
                        "FROM attempt WHERE body_hash=? AND verdict='SEND'",
                        (h,),
                    ).fetchone()
                    n_prev = int(prev["n"] or 0)
                    n_failed = int(prev["f"] or 0)
                    if n_prev > 0 and n_failed == n_prev and n_prev >= max_retries:
                        hold_rows = c.execute(
                            "SELECT attempt_id FROM attempt WHERE body_hash=? AND verdict='SEND' "
                            "ORDER BY attempt_id DESC LIMIT 5", (h,)).fetchall()
                        holds = [int(r["attempt_id"]) for r in hold_rows]
                        verdict, reason_code = "SUPPRESS", "retry-cap"
                        detail_t = ("SUPPRESS: retry cap reached -- %d previous attempts of "
                                    "this exact text all failed/undelivered, cap %d "
                                    "(attempt {aid})" % (n_failed, max_retries))
                    else:
                        gap_cut = _iso(now - timedelta(minutes=gap_min))
                        floor = c.execute(
                            "SELECT attempt_id, COALESCE(sent_at, at) AS ts FROM attempt "
                            "WHERE status IN ('sent','delivered') AND COALESCE(sent_at, at) >= ? "
                            "ORDER BY COALESCE(sent_at, at) DESC LIMIT 1",
                            (gap_cut,),
                        ).fetchone()
                        # A reply is SOLICITED: he is in a conversation, so the floor --
                        # which is a rule about unsolicited traffic -- does not hold it.
                        if (floor is not None and urgency not in URGENT_URGENCIES
                                and class_hint != REPLY_CLASS):
                            when = _parse(floor["ts"]) or now
                            holds = [int(floor["attempt_id"])]
                            verdict, reason_code = "FLOOR", "floor"
                            detail_t = ("FLOOR: a text was delivered to the owner %s ago; "
                                        "floor is %g min and urgency '%s' is below it "
                                        "(attempt {aid})" % (_ago((now - when).total_seconds()),
                                                             gap_min, urgency))
                        # THE COALESCE RULE WAS WITHDRAWN HERE (int-c, 2026-10-14).
                        # It returned verdict COALESCE with the detail "batched into the
                        # next 90-min digest window, not sent now" -- but no digest window
                        # and no coalescer exist anywhere in the estate, so the sentence
                        # was false and the message was refused for no reason.  Control
                        # now falls straight through to SEND.  `coalesce_min` above is
                        # left in place because `policy()` / `doctor()` still report
                        # OWNER_TEXT_RELAY_COALESCE_MINUTES; nothing in this decision
                        # reads it.
                        else:
                            verdict, reason_code = "SEND", "ok"
                            if dedupe_skipped:
                                detail_t = ("SEND: duplicate rules skipped (%s) -- for this class "
                                            "a duplicate is cheap and a miss is not; retry cap, "
                                            "floor and class rules still applied "
                                            "(urgency '%s', attempt {aid})"
                                            % ("subsystem %r is dedupe-exempt" % subsystem
                                               if dedupe_exempt else "caller asked",
                                               urgency))
                            else:
                                detail_t = ("SEND: nothing on record holds this text "
                                            "(urgency '%s', attempt {aid})" % urgency)

            cur = c.execute(
                "INSERT INTO attempt (at, door, subsystem, body, body_hash, reason, urgency, "
                "class_hint, ref, topic, opens_ask, verdict, verdict_reason, detail, holds, status, "
                "to_number) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (now_s, door, subsystem, body, h, "" if reason is None else str(reason), urgency,
                 class_hint, ref, topic, 1 if opens_ask else 0, verdict, reason_code, "",
                 json.dumps(holds), "pending", to),
            )
            aid = int(cur.lastrowid)
            detail = detail_t.format(aid=aid)
            c.execute("UPDATE attempt SET detail=? WHERE attempt_id=?", (detail, aid))

            ask_ref = None
            if opens_ask:
                ask_ref = ref or ("attempt-%d" % aid)
                _upsert_ask_tx(c, ask_ref, subsystem, topic or "", body,
                               ttl_hours=72.0, attempt_id=aid, now=now)
                c.execute("UPDATE attempt SET ref=?, opens_ask=1 WHERE attempt_id=?",
                          (ask_ref, aid))

            c.execute("COMMIT")
        except BaseException:
            try:
                c.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
    finally:
        owns.close()

    return {
        "verdict": verdict,
        "reason": reason_code,
        "attempt_id": aid,
        "detail": detail,
        "holds": holds,
        "body_hash": h,
        "at": now_s,
        "ask_ref": ask_ref,
        "urgency": urgency,
        "class_hint": class_hint,
        "door": door,
        "subsystem": subsystem,
        "dedupe_extra": dedupe_extra,
        "dedupe_disabled": bool(dedupe_disabled),
        "dedupe_exempt": bool(dedupe_exempt),
        "dedupe_skipped": bool(dedupe_skipped),
    }


# --------------------------------------------------------------------------
# outcome recording
# --------------------------------------------------------------------------

def record_sent(attempt_id: int, *, sid: str = "", status: str = "sent",
                body: str | None = None, conn=None) -> None:
    """Mark an attempt as sent/delivered.  `sid` is the transport message id.

    If `body` is given the delivered bytes are stored (a door that truncates on
    the way out records what the owner actually received).  The dedupe key
    body_hash is deliberately NOT recomputed: the policy key is the submitted
    body, so a later identical submission still dedupes against this one.
    """
    owns = _Conn(conn)
    c = owns.conn
    try:
        now_s = _iso(_now())
        sets = ["status=?", "sid=?", "sent_at=?", "failed_at=NULL"]
        args = [status, sid or "", now_s]
        if body is not None:
            sets.append("body=?")
            args.append(str(body))
        args.append(int(attempt_id))
        c.execute("UPDATE attempt SET %s WHERE attempt_id=?" % ", ".join(sets), args)
    finally:
        owns.close()


def record_failed(attempt_id: int, *, error: str = "", status: str = "failed",
                  conn=None) -> None:
    """Mark an attempt as failed/undelivered.  This is what arms the retry cap."""
    owns = _Conn(conn)
    c = owns.conn
    try:
        c.execute(
            "UPDATE attempt SET status=?, failed_at=?, error=? WHERE attempt_id=?",
            (status, _iso(_now()), "" if error is None else str(error), int(attempt_id)),
        )
    finally:
        owns.close()


# --------------------------------------------------------------------------
# asks
# --------------------------------------------------------------------------

def _ask_row_to_dict(row, now=None) -> dict:
    now = now or _now()
    asked = _parse(row["asked_at"])
    age = (now - asked).total_seconds() / 3600.0 if asked else None
    return {
        "ref": row["ref"],
        "subsystem": row["subsystem"],
        "topic": row["topic"],
        "body": row["body"],
        "asked_at": row["asked_at"],
        "age_hours": None if age is None else round(age, 3),
        "state": row["state"],
        "ttl_hours": row["ttl_hours"],
        "expires_at": row["expires_at"],
        "answer": row["answer"],
        "answered_at": row["answered_at"],
        "answered_by": row["answered_by"],
        "attempt_id": row["attempt_id"],
    }


def _upsert_ask_tx(c, ref, subsystem, topic, body, *, ttl_hours=72.0,
                   attempt_id=None, now=None) -> dict:
    """Insert-if-absent (idempotent on ref) inside the caller's transaction."""
    now = now or _now()
    existing = c.execute("SELECT * FROM ask WHERE ref=?", (ref,)).fetchone()
    if existing is not None:
        out = _ask_row_to_dict(existing, now)
        out["ok"] = True
        out["created"] = False
        return out
    asked_at = _iso(now)
    expires_at = _iso(now + timedelta(hours=float(ttl_hours)))
    c.execute(
        "INSERT INTO ask (ref, subsystem, topic, body, asked_at, ttl_hours, expires_at, "
        "state, attempt_id) VALUES (?,?,?,?,?,?,?,'open',?)",
        (ref, subsystem, topic, body, asked_at, float(ttl_hours), expires_at, attempt_id),
    )
    row = c.execute("SELECT * FROM ask WHERE ref=?", (ref,)).fetchone()
    out = _ask_row_to_dict(row, now)
    out["ok"] = True
    out["created"] = True
    return out


def record_ask(ref: str, subsystem: str, topic: str, body: str, *,
               ttl_hours: float = 72.0, conn=None) -> dict:
    """Open an ask, idempotent on `ref`.  Returns the ask (created True/False)."""
    owns = _Conn(conn)
    c = owns.conn
    try:
        c.execute("BEGIN IMMEDIATE")
        try:
            out = _upsert_ask_tx(c, ref, subsystem, topic, body, ttl_hours=ttl_hours)
            c.execute("COMMIT")
        except BaseException:
            try:
                c.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
    finally:
        owns.close()
    return out


def _expire_tx(c, now) -> int:
    cur = c.execute(
        "UPDATE ask SET state='expired' WHERE state='open' AND expires_at <= ?",
        (_iso(now),),
    )
    return int(cur.rowcount or 0)


def open_asks(*, within_hours: float = 72.0, conn=None) -> list:
    """Every open ask, oldest first.  Overdue rows are marked expired first."""
    owns = _Conn(conn)
    c = owns.conn
    try:
        c.execute("BEGIN IMMEDIATE")
        try:
            now = _now()
            _expire_tx(c, now)
            cut = _iso(now - timedelta(hours=float(within_hours)))
            rows = c.execute(
                "SELECT * FROM ask WHERE state='open' AND asked_at >= ? ORDER BY asked_at ASC",
                (cut,),
            ).fetchall()
            c.execute("COMMIT")
        except BaseException:
            try:
                c.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
    finally:
        owns.close()
    return [_ask_row_to_dict(r, now) for r in rows]


def answer_ask(ref: str, answer: str, *, answered_by: str = "owner", conn=None) -> dict:
    """Record the owner's answer against an ask (any state, including expired)."""
    owns = _Conn(conn)
    c = owns.conn
    try:
        c.execute("BEGIN IMMEDIATE")
        try:
            now = _now()
            row = c.execute("SELECT * FROM ask WHERE ref=?", (ref,)).fetchone()
            if row is None:
                c.execute("ROLLBACK")
                return {"ok": False, "reason": "unknown-ref", "ref": ref, "state": "missing"}
            previous = row["state"]
            now_s = _iso(now)
            c.execute(
                "UPDATE ask SET state='answered', answer=?, answered_at=?, answered_by=? WHERE ref=?",
                (answer, now_s, answered_by, ref),
            )
            updated = c.execute("SELECT * FROM ask WHERE ref=?", (ref,)).fetchone()
            c.execute("COMMIT")
        except BaseException:
            try:
                c.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
    finally:
        owns.close()
    out = _ask_row_to_dict(updated, now)
    out["ok"] = True
    out["previous_state"] = previous
    return out


def expire_asks(*, conn=None) -> int:
    """Mark every overdue open ask expired; returns how many changed."""
    owns = _Conn(conn)
    c = owns.conn
    try:
        c.execute("BEGIN IMMEDIATE")
        try:
            n = _expire_tx(c, _now())
            c.execute("COMMIT")
        except BaseException:
            try:
                c.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
    finally:
        owns.close()
    return n


def record_answer(ref: str, answer: str, *, conn=None) -> None:
    """Alias kept for callers that only want the side effect."""
    answer_ask(ref, answer, conn=conn)


# --------------------------------------------------------------------------
# status / doctor / availability
# --------------------------------------------------------------------------

def status(*, conn=None) -> dict:
    """What did we decide, and what did we decide NOT to tell him."""
    owns = _Conn(conn)
    c = owns.conn
    try:
        now = _now()
        path = db_path()
        cut24 = _iso(now - timedelta(hours=24))
        cut30 = _iso(now - timedelta(days=30))

        def verdict_counts(cut):
            out = {v: 0 for v in VERDICTS}
            for r in c.execute(
                "SELECT verdict, COUNT(*) AS n FROM attempt WHERE at >= ? GROUP BY verdict", (cut,)
            ):
                out[r["verdict"]] = int(r["n"])
            return out

        def reason_counts(cut):
            out = {}
            for r in c.execute(
                "SELECT verdict, verdict_reason, COUNT(*) AS n FROM attempt "
                "WHERE at >= ? AND verdict IN ('SUPPRESS','DEDUPE','FLOOR','TOO_LONG','COALESCE') "
                "GROUP BY verdict, verdict_reason ORDER BY n DESC", (cut,)
            ):
                out["%s/%s" % (r["verdict"], r["verdict_reason"])] = int(r["n"])
            return out

        total = int(c.execute("SELECT COUNT(*) AS n FROM attempt").fetchone()["n"])
        recent = [
            {
                "attempt_id": int(r["attempt_id"]),
                "at": r["at"],
                "verdict": r["verdict"],
                "reason": r["verdict_reason"],
                "door": r["door"],
                "subsystem": r["subsystem"],
                "detail": r["detail"],
                "body_80": (r["body"] or "")[:80],
            }
            for r in c.execute(
                "SELECT * FROM attempt WHERE verdict IN ('SUPPRESS','DEDUPE','TOO_LONG') "
                "ORDER BY attempt_id DESC LIMIT 10"
            )
        ]
        asks = {r["state"]: int(r["n"]) for r in c.execute(
            "SELECT state, COUNT(*) AS n FROM ask GROUP BY state")}
        for state in ("open", "answered", "expired"):
            asks.setdefault(state, 0)
        out = {
            "generated_at": _iso(now),
            "store": path,
            "policy": policy(),
            "attempts_total": total,
            "verdicts_24h": verdict_counts(cut24),
            "verdicts_30d": verdict_counts(cut30),
            "held_reasons_24h": reason_counts(cut24),
            "held_reasons_30d": reason_counts(cut30),
            "not_told_last_10": recent,
            "asks": asks,
        }
    finally:
        owns.close()
    return out


def doctor(*, conn=None) -> dict:
    """{"ok": bool, "checks": [{"name","ok","detail"}]}.  Never raises."""
    checks = []

    def add(name, ok, detail):
        checks.append({"name": name, "ok": bool(ok), "detail": str(detail)})

    path = db_path()
    add("store-path", True, path)
    exists = os.path.exists(path)
    add("store-exists", True, "exists" if exists else "not created yet (connect() will create it)")
    parent = os.path.dirname(os.path.abspath(path))
    ancestor = _writable_ancestor(path)
    add("store-dir-writable", bool(ancestor) and os.access(ancestor, os.W_OK),
        "%s %s" % (ancestor or parent,
                   "writable" if ancestor and os.access(ancestor, os.W_OK) else "NOT writable"))

    conn_ = conn
    owned = None
    try:
        if conn_ is None:
            owned = connect()
            conn_ = owned
        add("store-openable", True, "opened read-write")
    except Exception as exc:                                    # noqa: BLE001
        add("store-openable", False, "%s: %s" % (type(exc).__name__, exc))
        conn_ = None

    if conn_ is not None:
        try:
            names = {r[0] for r in conn_.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            want = {"attempt", "ask"}
            add("schema", want.issubset(names),
                "attempt=%s ask=%s" % ("attempt" in names, "ask" in names))
            idx = {r[0] for r in conn_.execute(
                "SELECT name FROM sqlite_master WHERE type='index'")}
            want_idx = {"idx_attempt_hash", "idx_attempt_status", "idx_attempt_at",
                        "idx_attempt_verdict", "idx_ask_state"}
            add("schema-indices", want_idx.issubset(idx),
                "missing=%s" % sorted(want_idx - idx) if not want_idx.issubset(idx)
                else "%d indices present" % len(want_idx))
        except Exception as exc:                                # noqa: BLE001
            add("schema", False, "%s: %s" % (type(exc).__name__, exc))

        try:
            mode = str(conn_.execute("PRAGMA journal_mode").fetchone()[0]).lower()
            add("journal-mode", mode == "wal", "journal_mode=%s" % mode)
        except Exception as exc:                                # noqa: BLE001
            add("journal-mode", False, "%s: %s" % (type(exc).__name__, exc))

        try:
            bt = int(conn_.execute("PRAGMA busy_timeout").fetchone()[0])
            add("busy-timeout", bt >= 5000, "busy_timeout=%d ms" % bt)
        except Exception as exc:                                # noqa: BLE001
            add("busy-timeout", False, "%s: %s" % (type(exc).__name__, exc))

        try:                                                    # write without committing
            conn_.execute("BEGIN IMMEDIATE")
            conn_.execute("ROLLBACK")
            add("store-writable", True, "acquired the write lock and rolled back")
        except Exception as exc:                                # noqa: BLE001
            try:
                conn_.execute("ROLLBACK")
            except Exception:                                   # noqa: BLE001
                pass
            add("store-writable", False, "%s: %s" % (type(exc).__name__, exc))

    raw_off = os.environ.get("OWNER_TEXT_RELAY_OFF")
    add("kill-switch", True,
        "OWNER_TEXT_RELAY_OFF=%r -> %s" % (raw_off, "policy BYPASSED, everything SEND"
                                           if raw_off == "1" else "policy active"))
    add("dedupe-exempt-subsystems", True,
        "DEDUPE_EXEMPT_SUBSYSTEMS = %s -> rules 3/3b skipped for these, without the "
        "caller asking" % (sorted(DEDUPE_EXEMPT_SUBSYSTEMS),))
    add("reply-class", True,
        "REPLY_CLASS = %r -> rule 5 (FLOOR) exempts this class_hint" % (REPLY_CLASS,))
    add("max-chars", True,
        "MAX_CHARS = %d (OWNER_TEXT_RELAY_MAX_CHARS) -> submit() returns TOO_LONG over "
        "this and fit() cuts to it; NO COALESCER EXISTS, so verdict COALESCE is retained "
        "only to read rows written before the rule was withdrawn" % (MAX_CHARS,))
    for row in policy_sources():
        add("policy.%s" % row["name"], True,
            "%s = %s (%s)" % (row["env"], row["value"], row["source"]))

    if owned is not None:
        owned.close()
    return {"ok": all(c["ok"] for c in checks), "checks": checks}


def available() -> bool:
    """True if this module can open its store right now.

    Pre-flight only: it creates the store on first call (connect() does), and it
    is NOT a substitute for the caller's try/except -- see the module docstring.
    """
    try:
        c = connect()
    except Exception:                                           # noqa: BLE001
        return False
    try:
        c.execute("SELECT 1 FROM attempt LIMIT 1")
        return True
    except Exception:                                           # noqa: BLE001
        return False
    finally:
        c.close()


if __name__ == "__main__":                                      # pragma: no cover
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "doctor":
        print(json.dumps(doctor(), ensure_ascii=False))
        raise SystemExit(0 if doctor()["ok"] else 1)
    print(json.dumps({"ok": True, "verdicts": list(VERDICTS), "store": db_path()}))
