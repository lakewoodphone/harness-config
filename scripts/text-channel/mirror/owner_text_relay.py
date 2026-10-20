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
                    OWNER_TEXT_MAX_CHARS               (default 400; the app's number)
                    OWNER_TEXT_RELAY_MAX_CHARS         (legacy relay-only override)
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
    * `MAX_CHARS` (default 400, the app's `OWNER_TEXT_MAX_CHARS` one-text
      policy) is the single ceiling, and `submit()` returns `TOO_LONG` for any
      body over it -- after the kill switch and BEFORE the duplicate rules, so a
      text that will never be sent does not burn a dedupe slot.  The attempt row
      is written like every other verdict.
    * `fit(body, limit=None)` is exported so a door can COMPLY instead of being
      refused: it cuts on a sentence, then a clause, then a word boundary (never
      mid-word when such a boundary exists in the window), appends the existing
      `TRUNCATION_MARKER` only when it actually truncated, and never returns more
      than the limit.
  A refusal is a lost message, so every wired door must call `fit()` BEFORE
  `submit()`; `TOO_LONG` is reachable only by a caller that skipped it.

THREE GUARDS, MEASURED FROM HIS OWN TEXTS (2026-10-19)
  Each is a different kind of fault, so each has its own verdict reason, its own
  kill switch, and its own place in the chain:

    quiet_hours        (rule 1f) the message was fine and the HOUR was not. 112 of
                       548 delivered outbound texts (20.4%) arrived 23:00-07:00
                       America/New_York, including reminders at 02:29, 02:55, 03:09.
                       Window 23:00-07:30 local, overridable by
                       OWNER_TEXT_QUIET_START / OWNER_TEXT_QUIET_END (HH:MM).
                       Bypassed by `urgency in INTERRUPTING_URGENCIES` (urgent,
                       critical, stuck -- the app gate's own set), by
                       `class_hint == REPLY_CLASS`, by a safety-critical subsystem,
                       and by the owner having texted us inside the last
                       OWNER_TEXT_QUIET_AWAKE_MINUTES (default 60): a reply to his own
                       midnight text must never be silenced by his own quiet hours.
                       IT DROPS; IT DOES NOT QUEUE.  See `quiet_hours_now`.
    credential_request (rule 1g) the body asked him to send a login, a password or a
                       code in writing. Two of these were delivered (2026-10-16 14:24,
                       2026-10-17 14:22). Requires a credential noun AND a request
                       verb before it in the SAME sentence, so "the login page is
                       broken" is a status report and stays a message.
    internal_prose     (rule 1h) the body was never addressed to a human: an
                       instruction to an agent (`EXECUTE:`, `Task #\\d+`, `present ONE
                       numbered`), a repo path (`docs/...`, `...md`), a budget or
                       exit-code string, a bare "Remembered.", or the first half of a
                       sentence. The reason names the class: `internal_prose:<class>`.

  ALL THREE FAIL OPEN AND ARE SWITCHABLE WITHOUT A DEPLOY: `OWNER_TEXT_GUARD_QUIET=0`,
  `OWNER_TEXT_GUARD_CREDENTIAL=0`, `OWNER_TEXT_GUARD_INTERNAL=0`. A wrong SUPPRESS here
  is a message he never sees, so a guard that cannot be evaluated records SEND and puts
  its reason in the attempt row's `detail`, a guard that raises allows the send and
  writes one line to stderr, and every decision is still written as an attempt row so
  `status()` counts it. No new table, no new column: an inbound row is an attempt row
  with `verdict='INBOUND'` (`record_inbound`), which `status()` reports separately
  because it is not a policy verdict -- it is the other direction of the conversation.

DEDUPE IS ALREADY DOOR-BLIND -- CHECKED, NOT ASSUMED (2026-10-19)
  Two senders delivered the same words minutes apart six times in one week (10-13
  02:08, 10-14 05:31, 10-18 05:46, 10-18 14:03, 10-19 01:25, 10-19 05:48) under
  `subsystem=sms_service.audit` and `subsystem=orchestrator`. Read before changing:
  `policy_hash` is `sha256(normalise(body) [+ "\n" + dedupe_extra])` -- neither the
  door nor the subsystem is anywhere in it -- and both duplicate queries filter on
  `body_hash` alone. There was nothing door-shaped to remove, so nothing was removed:
  the hash, the 6-hour window and the `dedupe_extra` contract are untouched, and
  `doctor()` now states the composition so the next reader does not have to re-derive
  it. The measured pairs therefore did not split on the door; the two causes this file
  can SEE are a per-door `dedupe_extra` supplied by a caller and
  `dedupe_disabled=True`, and neither is a reason to weaken the key here.
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
    "DEDUPE_EXEMPT_SUBSYSTEMS", "REPLY_CLASS", "INTERRUPTING_URGENCIES",
    "connect", "submit", "record_sent", "record_failed", "record_inbound",
    "record_ask", "open_asks", "answer_ask", "expire_asks", "record_answer",
    "status", "doctor", "available",
    "normalise", "body_hash", "policy", "policy_sources", "db_path", "fit",
    "quiet_hours_now", "credential_request", "internal_prose",
    "compose_reminder_sentence",
    "GUARD_ENV", "CREDENTIAL_CODE", "CREDENTIAL_RULE_TEXT", "INBOUND_VERDICT",
    "QUIET_START_DEFAULT", "QUIET_END_DEFAULT", "QUIET_AWAKE_DEFAULT",
]

DEFAULT_DB = "/root/.owner-text/relay.db"
VERDICTS = ("SEND", "DEDUPE", "FLOOR", "TOO_LONG", "COALESCE", "SUPPRESS")

#: The one owner-text ceiling.  The number is the app's (`app/owner_text.py`:
#: `DEFAULT_MAX_CHARS = 400`, overridden by `OWNER_TEXT_MAX_CHARS`), and the relay
#: is the only component that sees every door, so it reads the SAME name instead
#: of inventing a second default.  `OWNER_TEXT_RELAY_MAX_CHARS` is kept as a
#: legacy/emergency relay-only override, but the shared name always wins when both
#: are set, so the gate and the relay cannot silently disagree again.
#:
#: MEASURED 2026-10-18: the old 320 default cut a 361-char reminder to 307 and
#: dropped its final instruction ("If the card is there, hand it back and take no
#: money").  The gate had already judged the same body legal at 400.
#: Evaluated at import time, like the rest of this module's constants.
MAX_CHARS = int(
    os.environ.get("OWNER_TEXT_MAX_CHARS")
    or os.environ.get("OWNER_TEXT_RELAY_MAX_CHARS")
    or "400"
)

#: The ceiling for a message to someone who is NOT the owner. The owner's ceiling exists
#: because of how HE reads a text (his own words: "way too much information at once"), not
#: because of a transport limit -- so applying it to anyone who is not him was a
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

    The owner's ceiling is about how he reads a text, so it belongs to him alone; any other
    recipient gets the transport limit. This is a rule about the RECIPIENT, and the relay
    holds no opinion about which application a message came from (owner, 2026-10-18).

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
#: The urgencies that may wake the owner during quiet hours. This is the APP GATE's set
#: (`app/owner_text.INTERRUPTING_URGENCIES`, mirrored in textsend.py:778) and it is the app's
#: own words, quoted rather than re-derived: "urgent", "critical", "stuck". It is deliberately
#: one member WIDER than `URGENT_URGENCIES` above, which drives the rate floor and the floor
#: only -- "stuck" must be able to break the floor's silence at any hour, and `URGENT_URGENCIES`
#: is left exactly as it was so that no existing rule changes meaning.
INTERRUPTING_URGENCIES = frozenset({"urgent", "critical", "stuck"})
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
# THE THREE GUARDS HIS OWN TEXTS ASKED FOR (added 2026-10-19)
# --------------------------------------------------------------------------
#
# Three different kinds of fault, three different reason codes, one chain:
#
#   quiet_hours         the message was fine and the HOUR was not
#   credential_request  the message asked him for a login, in writing
#   internal_prose      the body was never addressed to a human at all
#
# EVERY GUARD FAILS OPEN. A guard that raises is a guard that stops a send, and the
# caller's try/except cannot help -- `submit()` is already inside it -- so the failure
# mode is chosen here instead: allow, print ONE line to stderr per process (the
# `_TOPIC_WARNED` convention), and hand the evidence back as a note that `submit()`
# writes into the attempt row's `detail`. A broken guard is then visible in the ledger,
# not only in a log nobody reads.
#
# EVERY GUARD IS SWITCHABLE WITHOUT A DEPLOY, because a wrong SUPPRESS is a message he
# never sees: OWNER_TEXT_GUARD_QUIET=0 / OWNER_TEXT_GUARD_CREDENTIAL=0 /
# OWNER_TEXT_GUARD_INTERNAL=0. The env is read on every submit, never at import, so
# clearing a false positive is a file edit in a sender that is already running rather
# than a redeploy of this module.
#
# AND NONE OF THEM MAY BE THE THING THAT LOSES A PAGE: every guard exempts the
# safety-critical subsystems in `DEDUPE_EXEMPT_SUBSYSTEMS`. That set exists because
# "the relay refuses to be the thing that loses a page", and a page's body is exactly
# what `internal_prose` is built to recognise (a machine sentence, often with a
# `data/...` snapshot path in it). The exemption is the same deliberate asymmetry, one
# rule further out.

GUARD_ENV = {
    "QUIET": "OWNER_TEXT_GUARD_QUIET",
    "CREDENTIAL": "OWNER_TEXT_GUARD_CREDENTIAL",
    "INTERNAL": "OWNER_TEXT_GUARD_INTERNAL",
}
#: Anything that plainly means "off". Everything else -- including unset and an empty
#: string -- leaves the guard ON, so the default is the documented behaviour and a typo
#: keeps the rule rather than silently disabling it.
_GUARD_OFF = frozenset({"0", "off", "false", "no", "disable", "disabled", "n"})
_GUARD_WARNED: set = set()


def _guard_on(name: str) -> bool:
    """Is this guard enabled right now? Read per call, so an env edit takes effect."""
    raw = os.environ.get(GUARD_ENV[name])
    if raw is None:
        return True
    return str(raw).strip().lower() not in _GUARD_OFF


def _guarded(label: str, fn, *args):
    """(value, error_note): `fn(*args)`, or (None, note) if it raised.

    The one place a guard is allowed to fail, and the only direction it may fail in.
    `print` is once per process per guard: this runs inside a tick loop, and a log storm
    is its own outage.
    """
    try:
        return fn(*args), ""
    except Exception as exc:                                    # noqa: BLE001
        if label not in _GUARD_WARNED:
            _GUARD_WARNED.add(label)
            print("owner-text relay: guard %s raised %s: %s -- allowing the send"
                  % (label, type(exc).__name__, exc), file=sys.stderr)
        return None, "guard %s could not be evaluated (%s: %s); allowed" % (
            label, type(exc).__name__, exc)


def _q(text, limit: int = 90) -> str:
    """A quoted fragment safe to put through `str.format()`: braces gone, one line.

    `submit()` fills `{aid}` with `str.format`, which re-scans every substituted value,
    so a body containing a brace would raise KeyError there -- a guard turning into a
    lost message by the back door. The braces are therefore replaced before the text can
    reach the format string.
    """
    s = " ".join(str(text if text is not None else "").split())
    s = s.replace("{", "(").replace("}", ")").replace('"', "'")
    if len(s) > limit:
        s = s[:limit].rstrip() + "..."
    return '"%s"' % s


def _owner_scope(to) -> bool:
    """True when this text is for the owner. An unstated recipient is him.

    Deliberately the same test `ceiling_for()` uses: every pre-existing caller omitted
    `to`, so silence means him. Quiet hours are his clock and internal prose is his
    reading experience; neither is imposed on a customer or a family member, whose
    messages are drafted by a human and must not have their behaviour changed here.
    """
    return (not to) or is_owner_number(to)


# ---- rule 1f: quiet hours -------------------------------------------------

QUIET_TZ = "America/New_York"
QUIET_START_ENV = "OWNER_TEXT_QUIET_START"
QUIET_END_ENV = "OWNER_TEXT_QUIET_END"
QUIET_AWAKE_ENV = "OWNER_TEXT_QUIET_AWAKE_MINUTES"
QUIET_START_DEFAULT = "23:00"
QUIET_END_DEFAULT = "07:30"
QUIET_AWAKE_DEFAULT = 60.0
QUIET_UNKNOWN = "quiet hours not evaluated"
_TZ_WARNED = False


def _nth_sunday(year: int, month: int, n: int) -> datetime:
    """The nth Sunday of a month (n=1 is the first), midnight, naive."""
    first = datetime(int(year), int(month), 1)
    return first + timedelta(days=(6 - first.weekday()) % 7) + timedelta(days=7 * (int(n) - 1))


def _ny_offset_hours(utc_naive: datetime) -> float:
    """-4.0 (EDT) or -5.0 (EST) for a naive UTC instant, by the US rule.

    DST starts at 02:00 LOCAL on the second Sunday in March (07:00Z, EST) and ends at
    02:00 LOCAL on the first Sunday in November (06:00Z, EDT), so the transition is
    computed in UTC from the UTC instant rather than by converting to a local time and
    reading the offset back out of THAT: the circular version is wrong for the hour
    before the March change and the hour after the November change (measured while
    writing this, 2026-10-19: it returned 02:59 for 2026-03-08T06:59Z, which is
    01:59 EST).
    """
    year = utc_naive.year
    start = _nth_sunday(year, 3, 2).replace(hour=2) + timedelta(hours=5)
    end = _nth_sunday(year, 11, 1).replace(hour=2) + timedelta(hours=4)
    return -4.0 if start <= utc_naive < end else -5.0


def _ny_local(now):
    """(naive America/New_York wall time, note) for a UTC datetime; (None, why) if not.

    zoneinfo first. The note is "" on that path and a sentence naming the fallback when
    the host has no zone database, so the reason string carries the degradation instead
    of hiding it.
    """
    global _TZ_WARNED
    if not isinstance(now, datetime):
        return None, "now is %r, not a datetime" % (type(now).__name__,)
    try:
        from zoneinfo import ZoneInfo
        return now.astimezone(ZoneInfo(QUIET_TZ)).replace(tzinfo=None), ""
    except Exception as exc:                                    # noqa: BLE001
        if not _TZ_WARNED:
            _TZ_WARNED = True
            print("owner-text relay: no %s zone database (%r); using a fixed US-Eastern "
                  "offset (UTC-4 in DST, UTC-5 outside)" % (QUIET_TZ, exc), file=sys.stderr)
    try:
        # A naive datetime is UTC by this store's convention; `.astimezone()` on a naive
        # one would silently mean "the host's local zone", which is the bug, not the fix.
        aware = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
        utc_naive = aware.astimezone(timezone.utc).replace(tzinfo=None)
    except Exception:                                           # noqa: BLE001
        return None, "now could not be converted to UTC"
    return (utc_naive + timedelta(hours=_ny_offset_hours(utc_naive)),
            " (no zone database on this host: fixed US-Eastern offset, UTC-4 in DST and "
            "UTC-5 outside it, by the US rule)")


def _hhmm(raw, default: str, name: str):
    """(minutes past midnight, "") from HH:MM; (None, why) when it is not HH:MM."""
    text = str(raw).strip() if raw is not None else ""
    if text == "":
        text = default
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", text)
    if not m:
        return None, "%s=%r is not HH:MM" % (name, text)
    hh, mm = int(m.group(1)), int(m.group(2))
    if mm > 59 or hh > 24 or (hh == 24 and mm != 0):
        return None, "%s=%r is not a time of day" % (name, text)
    return (0 if hh == 24 else hh * 60 + mm), ""


def _quiet_window():
    """(start_minutes, end_minutes, problem) -- 23:00-07:30 unless the env overrides."""
    start, p1 = _hhmm(os.environ.get(QUIET_START_ENV), QUIET_START_DEFAULT, QUIET_START_ENV)
    end, p2 = _hhmm(os.environ.get(QUIET_END_ENV), QUIET_END_DEFAULT, QUIET_END_ENV)
    problems = [p for p in (p1, p2) if p]
    return start, end, "; ".join(problems)


def quiet_hours_now(now) -> tuple:
    """(inside, reason) -- is `now` inside the owner's quiet hours?

    `inside` True means DO NOT SEND. `now` is a UTC datetime (this store's convention);
    a naive one is read as UTC.

    THE WINDOW. 23:00-07:30 America/New_York -- his clock, which is why the hours are
    these: he wakes around 11:00, works the shop 12:30-17:00, and 112 of 548 delivered
    outbound texts (20.4%) arrived between 23:00 and 07:00 local, including reminders at
    02:29, 02:55 and 03:09. Override the edges with OWNER_TEXT_QUIET_START /
    OWNER_TEXT_QUIET_END (HH:MM). The window may wrap midnight; start == end means no
    quiet hours at all, which is the only reading of a zero-length window that cannot
    silence a whole day.

    TIME ZONE. zoneinfo `America/New_York` when the host has a zone database, otherwise a
    fixed US-Eastern offset that still follows the US DST rule (-4 / -5) and SAYS SO in
    the reason, because a wrong hour must be diagnosable from the record.

    IT SUPPRESSES. IT DOES NOT QUEUE, AND IT MUST NOT BE "FIXED" INTO A QUEUE. Every
    sender on this channel is periodic -- a cron reminder, a tick-driven watcher, a
    heartbeat -- so a suppressed message comes back by itself, at an hour he is awake.
    A queue would hold everything that fired overnight and hand it over at 07:30 in one
    dump: twenty texts, none of them news, which is precisely the complaint ("way too
    much information at once", "36 items, 30 urgent") this system exists to stop.
    Dropping is correct, and the attempt row is the record that it happened.

    Cannot be evaluated -- an unparsable window, an unusable clock -- returns
    (False, "quiet hours not evaluated (...)") and the caller SENDS, with that sentence
    in the attempt's detail. A guard must never be the thing that loses a message.
    """
    start, end, problem = _quiet_window()
    local, tz_note = _ny_local(now)
    if local is None:
        return False, "%s (%s); sending" % (QUIET_UNKNOWN, tz_note or "unusable clock")
    if problem or start is None or end is None:
        return False, "%s (%s); sending" % (QUIET_UNKNOWN, problem or "unusable window")
    minutes = local.hour * 60 + local.minute
    window = "%02d:%02d-%02d:%02d" % (start // 60, start % 60, end // 60, end % 60)
    where = "%02d:%02d %s in %s" % (local.hour, local.minute, local.strftime("%a"), QUIET_TZ)
    if start == end:
        return False, "no quiet hours configured (%s, start == end); sending" % window
    if start > end:                                   # the window wraps midnight
        inside = minutes >= start or minutes < end
    else:
        inside = start <= minutes < end
    if inside:
        return True, "%s is inside quiet hours %s%s; he is asleep" % (where, window, tz_note)
    return False, "%s is outside quiet hours %s%s" % (where, window, tz_note)


# ---- rule 1g: never ask for a credential over SMS -------------------------

CREDENTIAL_CODE = "credential_request"
CREDENTIAL_RULE_TEXT = "a credential must be collected on a screen, never in a text"

#: The nouns. `login` covers "log in" and "login"; the rest are the shapes the two
#: measured messages used and their obvious siblings.
_CRED_NOUN_RE = re.compile(
    r"\b(?:log\s?in|login|username|user\s?name|user\s?id|userid|password|passcode|"
    r"pass\s?code|2fa|two[\s-]?factor|one[\s-]?time\s+code|otp|api\s+key|"
    r"account\s+number\s+and\s+routing)\b", re.IGNORECASE)
#: `pin` and `secret` are ordinary English verbs and adjectives ("pin down the date",
#: "keep this secret"), so they only count as credentials behind a determiner or an
#: account word: "your pin", "the wifi pin", "the client secret".
_CRED_WEAK_RE = re.compile(r"\b(?:pin|secret)\b", re.IGNORECASE)
_CRED_WEAK_OK_RE = re.compile(
    r"(?:\b(?:your|the|my|a|an|its|their|account|wifi|portal|admin|root|four|six|4|6|"
    r"log[- ]?in|-digit)\s+)$", re.IGNORECASE)
#: A request, not a report. "send" before the noun covers "send me your login" and
#: "can you send me the password"; the interrogative covers "what is the password for X".
#: `please` counts ONLY immediately before an ask verb -- "please send me the password" is
#: an ask, "please reset the password" is a task for us and must stay a message. For the
#: same reason there is no bare "can you" here: "can you reset the password" is a task,
#: and "can you send me the password" is already caught by "send".
_CRED_REQUEST_RE = re.compile(
    r"\b(?:give|gimme|need|needs|send|text|tell|provide|share|supply|forward|confirm|"
    r"enter|type|paste|let\s+me\s+have)\b"
    r"|\bplease\s+(?:send|give|text|tell|provide|share|forward|supply|paste|type)\b"
    r"|\bwhat(?:'s| is)\b|\bi.ll\s+need\b", re.IGNORECASE)
#: A credential noun immediately followed by one of these is describing a SYSTEM, not
#: asking for a secret: "the login page is broken" is a status report and must stay a
#: message, and so is "confirm the password is correct". This is the bound that keeps the
#: rule from eating bug reports and work instructions.
_CRED_DESCRIPTOR_RE = re.compile(
    r"^\s*(?:page|screen|form|field|link|url|portal|button|reset|flow|prompt|issue|"
    r"problem|broken|error|expired|changed|works|worked|times\s+out|"
    r"is\s+(?:broken|working|correct|right|live|active|set|up|fine|wrong)|"
    r"was\s+reset|has\s+changed)\b", re.IGNORECASE)
#: A negated verb is not a request ("do not send me the password").
_CRED_NEGATION_RE = re.compile(
    r"\b(?:not|never|don'?t|doesn'?t|cannot|can't|won'?t|isn'?t|aren'?t|avoid)\b",
    re.IGNORECASE)
_CRED_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+|\n+")


def credential_request(body) -> str:
    """The credential phrase this body ASKS for, or None. "None" means: not a request.

    Both halves are required, in the SAME sentence:

      * a credential noun (login, password, passcode, pin, username, user id, 2fa,
        one-time code, otp, api key, secret, account number and routing), and
      * a request verb -- give, need, send, tell, provide, share, confirm, please,
        what is, can you, could you -- appearing BEFORE the noun, so the noun is what is
        being asked for.

    Requiring the verb to come first is what separates the two measured messages
    ("Give me the NJ Premier Business Services login and I will file 06/2026 now" --
    delivered 2026-10-16 14:24) from a status report ("The login page ... is broken and
    I cannot file"). A sentence that says "the password was reset, please try again" has
    the verb after the noun and is not an ask.

    Two further bounds, both measured against the obvious false positives:
    a credential noun followed by a system word ("login page", "password reset") is
    describing a system, and a negated verb ("do not send me the password") is not an
    ask. `pin`/`secret` only count behind a determiner, so "pin down the date" is safe.

    A false positive here is a real message he never sees, so the rule is deliberately
    narrow: an elliptical ask ("Password for the router?") is MISSED rather than guessed
    at, which is the cheap direction of this trade.
    """
    text = "" if body is None else str(body)
    if not text.strip():
        return None
    for sentence in _CRED_SENTENCE_RE.split(text):
        found = []
        for m in _CRED_NOUN_RE.finditer(sentence):
            found.append(m)
        for m in _CRED_WEAK_RE.finditer(sentence):
            if _CRED_WEAK_OK_RE.search(sentence[:m.start()]):
                found.append(m)
        for noun in sorted(found, key=lambda x: x.start()):
            if _CRED_DESCRIPTOR_RE.search(sentence[noun.end():]):
                continue
            for verb in _CRED_REQUEST_RE.finditer(sentence[:noun.start()]):
                between = sentence[verb.end():noun.start()]
                before = sentence[max(0, verb.start() - 20):verb.start()]
                if _CRED_NEGATION_RE.search(between):
                    continue
                if re.search(r"\b(?:not|never|don'?t)\b\s*$", before, re.IGNORECASE):
                    continue
                return noun.group(0)
    return None


# ---- rule 1h: internal prose is not a message to a human ------------------

#: A repository or filesystem path. The leading `(?<![\w@])` keeps "mydocs/" out and the
#: trailing class is what makes "lpt-hub/docs/" (a DIRECTORY, as measured) match as well
#: as ".../groin-skin-condition.md".
_INTERNAL_PATH_RE = re.compile(
    r"(?<![\w@])~?/?(?:docs|data|lpt-hub|opt|srv|root|home|var|tmp|etc)/[\w./-]+"
    r"|\b[\w-]+(?:/[\w.-]+)*\.(?:md|py|json|sql|db|log|tsv|csv|ya?ml|sh|txt)\b"
    r"|\bbranch\s+[\w./-]+"
    r"|~/[.\w][\w./-]*", re.IGNORECASE)
#: An instruction to an agent, not a sentence for a reader. `Do NOT` is matched
#: case-SENSITIVELY: an agent instruction is written that way, and "Do not forget the
#: receipt" in a human message is a real sentence.
#: HARD instructional shapes: an agent instruction and nothing else. These fire always.
_INTERNAL_INSTRUCTION_RE = re.compile(
    r"\bEXECUTE:"
    r"|\bpresent\s+(?:ONE|one)\s+numbered\b"
    r"|(?:^|[.!?]\s+|\n\s*)(?-i:Do NOT)\b"
    r"|(?:^|[.!?]\s+|\n\s*)Record\b[^.\n]{0,80}\bin\b"
    r"|\bappend\b[^.\n]{0,40}\bto\b", re.IGNORECASE)
#: A machine string that escaped into his phone.
_INTERNAL_MACHINE_RE = re.compile(
    r"\[Budget exceeded|Traceback\s*\(most recent call|error 21617|\[exit code",
    re.IGNORECASE)
#: A body OPENED with somebody else's name and a dash: "Dov - for Yitz's ...". Measured
#: delivered to him, and it is addressed to a person who is not the reader.
_INTERNAL_ADDRESSED_RE = re.compile(r"^([A-Z][a-z]{1,9})\s*[-\u2013\u2014]\s+\S")
#: A WORD AND A DASH IS NOT A NAME. Measured by replay: the rule above fired on
#: "Done - reminder set", "No - I haven't created", "Understood - full autonomy", "Ha - no
#: fights" and "Understood - DSH is down" - all of them messages TO him, five of which he
#: answered. A human message may open with a capitalised word and a dash; only a word that
#: could be somebody's name makes it "addressed to a third party".
_NOT_A_NAME = frozenset("""
done no yes hi hey ha understood ok okay sure right got perfect great alright correct agreed
thanks thank well so but now here that this it and or if when confirmed noted good fine cool
yep nope hmm wow sorry updated added saved sure thing ya yeah
""".split())
#: An ID on its own is not an instruction. `Task #n` / `WO<n>` becomes one only beside an
#: imperative about the work, and never inside a question put to him.
_INTERNAL_ID_RE = re.compile(r"\bTask\s*#\d+|\bWO\d{8,}\b", re.IGNORECASE)
_IMPERATIVE_WORK_RE = re.compile(
    r"\b(?:write|hand|mail|record|append|execute|send|call|file|drop|collect|prepare|"
    r"complete|update|enter|submit|post|pay)\b[^.!?\n]{0,60}\b(?:and|or|the|it|them)\b",
    re.IGNORECASE)
_QUESTION_TO_HIM_RE = re.compile(
    r"\?\s*$|reply to this text|let me know|yes\?|\?\s*$", re.IGNORECASE)
#: Names that are the reader, not a third party.
_OWNER_NAME_WORDS = frozenset({"eliyahu", "eli", "zabz", "daniel", "lakewood"})
#: Words a complete sentence cannot end with. A comma is here at any length, so is the
#: brief's list; the copulas and auxiliaries were added because the measured half-message
#: ends with "is" ("... the contact block you supplied is", 78 chars) and no list of
#: conjunctions would ever catch it.
_INTERNAL_TAIL_RE = re.compile(
    r"(?:[,;:]|\b(?:and|the|with|to|of|for|in|on|at|by|from|is|are|was|were|be|been|"
    r"being|has|have|had|will|would|can|could|should|must|do|does|did|that|which|"
    r"your|our|their|its|my|a|an|if|when|while|because|so|but|or))\s*$", re.IGNORECASE)
#: What a finished message may end with. A colon is NOT here: "Here is what I need:" with
#: nothing after it is the half-message class, not a complete thought.
_INTERNAL_TERMINAL_RE = re.compile(r"[.!?\u2026\"'\u201d\u2019)\]]$")
#: A body that is nothing but an acknowledgement. `submit()` already refuses to count it
#: as content; the owner still received "Remembered." and "Captured as a task."
_INTERNAL_ACK_WORDS = frozenset({
    "remembered", "captured as a task", "captured", "got it", "understood", "noted",
    "ok", "okay", "on it", "will do", "ack",
})
_INTERNAL_ACK_SPLIT_RE = re.compile(r"[.!?,;\u2014]+\s*")


def _internal_ack(text: str) -> bool:
    """"Remembered." / "Got it." / "Let me look into that." -- no content, no result.

    The `let me` half is bounded by 90 characters, no digit and no question mark: an
    intention with no result is not a message, and one that names an amount or asks
    something is.
    """
    t = " ".join(text.split())
    if not t or len(t) > 90:
        return False
    parts = [p.strip().lower() for p in _INTERNAL_ACK_SPLIT_RE.split(t) if p.strip()]
    if parts and all(p in _INTERNAL_ACK_WORDS for p in parts):
        return True
    if re.match(r"(?i)^let me\b", t) and not re.search(r"\d", t) and "?" not in t:
        return True
    return False


def _internal_truncation(text: str):
    """Why this body reads as the first half of a message, or None."""
    b = text.rstrip()
    if not b:
        return None
    words = b.split()
    if len(b) >= 25 and len(words) >= 4 and _INTERNAL_TAIL_RE.search(b):
        return "ends with %r, a word no sentence ends on" % (words[-1][-16:],)
    # A body that ends on a NUMBER reads as finished ("... the confirmation number is
    # 4471"); every measured half-message stops on a WORD ("... you supplied is"). A
    # trailing digit is therefore accepted as a complete ending: a fragment that happens
    # to end in a figure escapes this rule, which is the cheap direction of the trade.
    if (len(b) > 200 and "?" not in b and not b[-1].isdigit()
            and not _INTERNAL_TERMINAL_RE.search(b)):
        return "ends %r with no terminal punctuation and no question mark" % (b[-24:],)
    return None


def _internal_hit(body):
    """(class, evidence) for the first internal-prose shape this body matches, else None.

    Class order is deliberate. A PATH is the most specific and most quotable evidence
    (and names the sensitive thing -- a health file, a wages table); an INSTRUCTION is
    the next strongest; then a machine string; then a body addressed to somebody else;
    then a bare acknowledgement; then a truncated fragment.
    """
    text = "" if body is None else str(body)
    if not text.strip():
        return None
    for cls, rx in (("path", _INTERNAL_PATH_RE),
                    ("instruction", _INTERNAL_INSTRUCTION_RE),
                    ("machine", _INTERNAL_MACHINE_RE)):
        m = rx.search(text)
        if m:
            return cls, m.group(0)
    # An ID-only match. Three things must all hold for it to be an instruction:
    #   * the body is not a question put to HIM (a security question keeps its task id),
    #   * it carries an imperative about the work ("write and hand", "record", "append"),
    #   * and it is not merely quoting the id as evidence in an answer.
    m = _INTERNAL_ID_RE.search(text)
    if m and not _QUESTION_TO_HIM_RE.search(text) and _IMPERATIVE_WORK_RE.search(text):
        return "instruction", m.group(0)
    m = _INTERNAL_ADDRESSED_RE.match(text)
    if m and m.group(1).lower() not in _OWNER_NAME_WORDS \
            and m.group(1).lower() not in _NOT_A_NAME:
        return "addressed", m.group(0)
    if _internal_ack(text):
        return "ack", " ".join(text.split())[:60]
    why = _internal_truncation(text)
    if why:
        return "truncated", why
    return None


def internal_prose(body) -> str:
    """The reason this body is internal prose, or None. `internal_prose:<class> -- <why>`.

    The first whitespace-delimited token is the reason CODE (`internal_prose:path`,
    `internal_prose:instruction`, `internal_prose:machine`, `internal_prose:addressed`,
    `internal_prose:ack`, `internal_prose:truncated`) and the rest is the evidence, with
    the matched text quoted, so `status()` groups on the code without this string being
    parsed twice.

    Detects, with the match quoted:
      * a repository or file path -- `docs/...`, `data/...`, `lpt-hub/...`, `~/.`, a
        `.md`/`.py`/`.json` filename, `branch ...`;
      * a work-order or agent instruction -- `EXECUTE:`, `Task #\\d+`, `WO` + 8 digits,
        `present ONE numbered`, `Do NOT`, `Record ... in`, `append to`;
      * a machine string -- `[Budget exceeded`, `Traceback`, `error 21617`, `[exit code`;
      * a body opened with a third party's name and a dash -- "Dov - for Yitz's ...";
      * a content-free acknowledgement -- the whole body is "Remembered.", "Got it.",
        "Captured as a task.", "On it." ... or a bare "Let me ..." with no result;
      * a truncated fragment -- ends on a comma or a word no sentence ends on, or runs
        past 200 characters with no terminal punctuation and no question mark.

    This is what the measured half-messages and agent instructions look like on a phone:
    `present ONE numbered owner-approval ask`, `Record date+amount in lpt-hub/docs/...`,
    `[Budget exceeded for : ceoreserveexhausted]`, `Captured as a task.`, and one body
    that simply stopped at "the contact block you supplied is".
    """
    hit = _internal_hit(body)
    if hit is None:
        return None
    cls, why = hit
    return "internal_prose:%s \u2014 %s" % (cls, why)


# ---- rule 1f's second bypass: he is awake, so the window is open ----------

#: The verdict an inbound row carries. Not a policy verdict -- it is the OTHER DIRECTION
#: of the conversation, recorded in the same table so one query answers "did he text us
#: recently". `status()` reports it separately for exactly that reason.
INBOUND_VERDICT = "INBOUND"
#: `door` values that mean "this row is a text FROM him". A door that records his inbound
#: text should use `record_inbound()`, which writes `verdict='INBOUND'`; these names are
#: accepted as well so a caller that already writes its own rows is not invisible.
INBOUND_DOORS = ("inbound", "owner-inbound", "sms_inbox", "sms-inbox", "owner-inbox")


def record_inbound(body: str = "", *, door: str = "inbound",
                   subsystem: str = "owner-inbound", at=None, sid: str = "",
                   conn=None) -> dict:
    """Record a text the OWNER sent us, so quiet hours can see that he is awake.

    WRITE THIS FROM THE INBOUND DOOR. Without it, quiet hours cannot know he is awake,
    and a reply to his own 00:30 text would wait until 07:30 -- his hours silencing his
    own conversation. `class_hint=REPLY_CLASS` also opens the window, for a door that
    already marks replies, but the marker this function writes is the direct answer.

    The row is an `attempt` row with `verdict='INBOUND'` and `status='pending'`. It is
    invisible to the duplicate rules (which require `sent`/`delivered`, or `pending` with
    `verdict='SEND'`), to the retry cap (`verdict='SEND'`), and to the floor
    (`sent`/`delivered`), so recording his side of the conversation cannot suppress ours.

    FAILS SOFT: an inbound path must not break because the relay store is unwell. Returns
    {"ok": bool, "attempt_id"|None, "at", "error"}.
    """
    text = "" if body is None else str(body)
    when = at or _now()
    at_s = _iso(when)
    owns = None
    try:
        owns = _Conn(conn)
        cur = owns.conn.execute(
            "INSERT INTO attempt (at, door, subsystem, body, body_hash, reason, urgency, "
            "class_hint, ref, topic, opens_ask, verdict, verdict_reason, detail, holds, "
            "status, to_number) "
            "VALUES (?,?,?,?,?,'','normal',NULL,NULL,NULL,0,?,?,?,'[]','pending','')",
            (at_s, str(door), str(subsystem), text, policy_hash(text),
             INBOUND_VERDICT, "inbound",
             "inbound text from the owner, recorded so quiet hours can see he is awake"
             + (" (sid %s)" % sid if sid else "")),
        )
        return {"ok": True, "attempt_id": int(cur.lastrowid), "at": at_s, "error": ""}
    except Exception as exc:                                    # noqa: BLE001
        print("owner-text relay: inbound text not recorded (%r); quiet hours cannot see "
              "it" % (exc,), file=sys.stderr)
        return {"ok": False, "attempt_id": None, "at": at_s, "error": str(exc)}
    finally:
        if owns is not None:
            owns.close()


def _inbound_minutes_ago(c, now):
    """Minutes since the newest row that is a text FROM the owner, or None.

    Read-only, and bounded to the last two days: this question is only ever "in the last
    hour", and a full scan of a year of attempts to answer it would be a cost on the
    owner's send path.
    """
    cols = {r[1] for r in c.execute("PRAGMA table_info(attempt)")}
    marks = ["verdict = ?"]
    args: list = [INBOUND_VERDICT]
    if "direction" in cols:
        marks.append("lower(COALESCE(direction, '')) = 'inbound'")
    if INBOUND_DOORS:
        marks.append("lower(COALESCE(door, '')) IN (%s)" % ",".join("?" * len(INBOUND_DOORS)))
        args.extend(INBOUND_DOORS)
    row = c.execute(
        "SELECT MAX(at) AS ts FROM attempt WHERE (%s) AND at >= ?" % " OR ".join(marks),
        tuple(args) + (_iso(now - timedelta(days=2)),),
    ).fetchone()
    newest = _parse(row["ts"] if row is not None else None)
    if newest is None:
        return None
    if newest.tzinfo is None:
        newest = newest.replace(tzinfo=timezone.utc)
    return max(0.0, (now - newest).total_seconds() / 60.0)


def _awake_minutes():
    """(minutes, problem) from OWNER_TEXT_QUIET_AWAKE_MINUTES, default 60."""
    raw = os.environ.get(QUIET_AWAKE_ENV)
    if raw is None or str(raw).strip() == "":
        return QUIET_AWAKE_DEFAULT, ""
    try:
        value = float(str(raw).strip())
    except (TypeError, ValueError):
        return QUIET_AWAKE_DEFAULT, "%s=%r is not a number; using %g" % (
            QUIET_AWAKE_ENV, raw, QUIET_AWAKE_DEFAULT)
    if value < 0:
        return QUIET_AWAKE_DEFAULT, "%s=%r is negative; using %g" % (
            QUIET_AWAKE_ENV, raw, QUIET_AWAKE_DEFAULT)
    return value, ""


def _quiet_guard(c, now, urgency, class_hint, to, subsystem):
    """(hit, notes) for rule 1f. `hit` is {"why": reason} when the send must be dropped.

    The bypasses, each for its own reason:
      * urgency in INTERRUPTING_URGENCIES -- "urgent", "critical", "stuck" may wake him;
      * a safety-critical subsystem (`DEDUPE_EXEMPT_SUBSYSTEMS`) -- the relay refuses to
        be the thing that loses a page, and a page is a page at 03:00;
      * `class_hint == REPLY_CLASS` -- a reply answers something he said, and the floor
        already exempts that class for the same reason;
      * he texted us inside OWNER_TEXT_QUIET_AWAKE_MINUTES -- his hours must never
        silence an answer to his own text.

    An error in the AWAKE check ALLOWS the send and says so: the safe direction for a
    guard that cannot read the store is "do not suppress", never "assume he is asleep".
    """
    notes: list = []
    if not _guard_on("QUIET"):
        return None, notes
    if not _owner_scope(to):
        return None, notes
    if subsystem in DEDUPE_EXEMPT_SUBSYSTEMS:
        return None, notes
    if urgency in INTERRUPTING_URGENCIES:
        return None, notes
    if class_hint == REPLY_CLASS:
        return None, notes
    got, err = _guarded("quiet", quiet_hours_now, now)
    if err:
        return None, [err]
    inside, why = got if got else (False, "")
    if str(why).startswith(QUIET_UNKNOWN):
        return None, [why]
    if not inside:
        return None, notes
    awake_min, problem = _awake_minutes()
    if problem:
        notes.append(problem)
    minutes, err = _guarded("quiet-awake", _inbound_minutes_ago, c, now)
    if err:
        # Fail OPEN: a guard that cannot tell whether he is awake must not assume sleep.
        return None, notes + [err]
    if minutes is not None and minutes <= awake_min:
        notes.append("quiet hours open: he texted us %s ago" % _ago(minutes * 60.0))
        return None, notes
    return {"why": why}, notes


# ---- rule 1h's rescue: a reminder is rewritten, never dropped ------------------

#: Bodies this may touch. A clock or siren opener is what this system's own reminder composer
#: puts on the wire; anything else is a different class and is left to the guard.
_REMINDER_OPENERS = ("\u23f0", "\U0001f6a8", "reminder:", "reminder -")
#: Scaffolding removed from a reminder body. Each of these is an instruction to an agent, or a
#: reference only an agent can follow, and none of them helps the owner do the thing.
_RESCUE_DROP_SENTENCE = re.compile(
    r"(?:docs/|data/|lpt-hub/|branch\s|\bRecord\b[^.]{0,80}\bin\b|\bappend\b[^.]{0,40}\bto\b"
    r"|\.md\b|\.py\b|\.json\b|\bWO\d{8,}\b|\bTask\s*#\d+"
    r"|\bDo NOT\b|\bNOT approved\b|\bproduction note\b|\bget the owner's\b)",
    re.IGNORECASE)
_RESCUE_DROP_PAREN = re.compile(r"\s*\([^)]*(?:docs/|data/|lpt-hub/|branch\s|\.md\b|\.py\b"
                                r"|\bRecord\b|\bTask\s*#\d+|\bWO\d{8,})[^)]*\)")
_RESCUE_STRIP_PREFIX = re.compile(r"\bEXECUTE:\s*|\bTask\s*#\d+:?\s*|\bWO\d{8,}\b\s*:?\s*",
                                 re.IGNORECASE)
_RESCUE_MAX = 280


def _is_reminder_class(body: str) -> bool:
    low = " " + " ".join(str(body or "").lower().split()) + " "
    return any(op in low for op in _REMINDER_OPENERS)


# ---- THE REMINDER COMPOSER: one human sentence, never a work order -------------
#
# Measured 2026-10-10: the owner received
#   "⏰ Reminder: VS Code session: present ONE numbered owner-approval ask — (1) #27836 ..."
# It is a reminder, so it must not be dropped (a suppressed reminder is a deleted
# reminder), but its body is an instruction to an agent wearing a clock emoji.  The
# sender had no composer: it prefixed "⏰ Reminder: " to whatever the model wrote and
# handed it to the gate, which refused it.  This is the missing composer.  It keeps the
# reminder's substance, writes ONE sentence a person can read, and removes exactly the
# three things the guard is right to refuse: paths, task ids and agent imperatives.
#
# It is shared on purpose: the app's sender calls it before the body exists, and
# `_rescue_reminder` calls it for a reminder already on the wire.  One composer, so the
# sentence the owner receives and the sentence the census scores cannot disagree.
_REMINDER_PREFIX_RE = re.compile(
    r"^\s*(?:[\u23f0\U0001f6a8\u26a0\ufe0f]+\s*)?(?:reminder|alert)\s*[:\-\u2014]\s*",
    re.IGNORECASE)
_REMINDER_TASK_ID_RE = re.compile(
    r"(?:#\s*\d{3,}|\b(?:task|item|row|issue|ledger|ticket|wo)\s*#?\s*\d{3,}\b)",
    re.IGNORECASE)
_REMINDER_PATH_RE = re.compile(
    r"(?<![\w@])~?/?(?:docs|data|lpt-hub|opt|srv|root|home|var|tmp|etc)/[\w./-]+"
    r"|\b[\w-]+(?:/[\w.-]+)*\.(?:md|py|json|sql|db|log|tsv|csv|ya?ml|sh|txt)\b",
    re.IGNORECASE)
#: A sentence that is meta-instruction or channel bookkeeping, not the reminder itself.
_REMINDER_META_RE = re.compile(
    r"(?:owner answers numbered lists|present\s+(?:ONE|one)\s+numbered|"
    r"re-?surface\s+as|surface\s+in\s+(?:the\s+)?next\s+vs\s*code\s+session|"
    r"ask\s+in\s+(?:the\s+)?next\s+vs\s*code\s+session|"
    r"logged\s+for\s+(?:the\s+)?next|sms\s+rate\s*limit|rate\s*limit\s+hit|"
    r"do\s+not\s+text\s+owner|next\s+vs\s*code\s+session)",
    re.IGNORECASE)
#: A clause that tells an agent what to do, not a fact for the reader.
_REMINDER_IMPERATIVE_RE = re.compile(
    r"\b(?:present|record|append|surface|re-?surface|execute|re-?run)\b[^.;\n]{0,90}",
    re.IGNORECASE)
_REMINDER_LIST_RE = re.compile(r"(?:^|\s)\((\d{1,2})\)\s+")
_REMINDER_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
_REMINDER_COUNT_WORDS = {1: "One", 2: "Two", 3: "Three", 4: "Four", 5: "Five",
                         6: "Six", 7: "Seven", 8: "Eight", 9: "Nine", 10: "Ten"}
_REMINDER_FALLBACK = "A reminder is due; the details are on your dashboard."


def _reminder_clean(text: str) -> str:
    """Strip the three refused shapes from one clause and close its punctuation."""
    t = " ".join(str(text or "").split())
    t = _REMINDER_TASK_ID_RE.sub("", t)
    t = _REMINDER_PATH_RE.sub("", t)
    t = re.sub(r"\(\s*\)|\[\s*\]", "", t)
    t = re.sub(r"\s+([,.;:])", r"\1", t)
    t = t.strip(" \t,;:-\u2014")
    return t


def _reminder_sentence(text: str) -> str:
    """Collapse a finished body into ONE sentence, or "" when nothing readable remains."""
    t = _reminder_clean(text)
    if not t:
        return ""
    t = re.sub(r"\.{2,}", ".", t)
    t = t[0].upper() + t[1:]
    if t[-1] not in ".!?":
        t += "."
    return t


def compose_reminder_sentence(body) -> tuple[str, str]:
    """(sentence, note). ONE human sentence for a reminder; never a path, id or imperative.

    The list form is kept because it is what the owner was being asked to answer: four
    numbered approval items become "Four things need your approval: ..., ..., and ...".
    Everything else keeps its first substantive sentence.  If nothing readable survives,
    the reminder is still delivered as a sentence pointing at the dashboard -- the
    reminder is not lost, and no machine text reaches the phone.
    """
    text = "" if body is None else str(body)
    if not text.strip():
        return "", "composer: empty reminder"
    work = _REMINDER_PREFIX_RE.sub("", text)
    # Numbered packets: the lead is an instruction, the items are the substance.
    matches = list(_REMINDER_LIST_RE.finditer(work))
    if len(matches) >= 2:
        items = []
        for idx, match in enumerate(matches):
            end = matches[idx + 1].start() if idx + 1 < len(matches) else len(work)
            item = work[match.end():end]
            # A trailing meta sentence belongs to the message, not to item N.
            item = _REMINDER_SENTENCE_SPLIT_RE.split(item)[0]
            item = _reminder_clean(item)
            if item and not _REMINDER_META_RE.search(item):
                items.append(item)
        if len(items) >= 2:
            noun = "approval" if re.search(r"approv", text, re.I) else "attention"
            n = len(items)
            lead = "%s thing%s need%s your %s" % (
                _REMINDER_COUNT_WORDS.get(n, str(n)), "" if n == 1 else "s",
                "s" if n == 1 else "", noun)
            kept = []
            for item in items:
                candidate = ", ".join(kept + [item])
                if len(lead) + len(candidate) + 8 <= _RESCUE_MAX:
                    kept.append(item)
            if len(kept) >= 2:
                joined = ", ".join(kept[:-1]) + " and " + kept[-1]
                sentence = _reminder_sentence("%s: %s" % (lead, joined))
                if sentence and _internal_hit(sentence) is None:
                    return sentence, ("composer: %d-item reminder written as one sentence "
                                      "(%d -> %d chars)" % (n, len(text), len(sentence)))
    # No usable list: drop meta/imperative sentences, keep the first substantive one.
    kept = []
    for part in _REMINDER_SENTENCE_SPLIT_RE.split(" ".join(work.split())):
        part = part.strip()
        if not part or _REMINDER_META_RE.search(part):
            continue
        part = _REMINDER_IMPERATIVE_RE.sub("", part)
        part = _reminder_clean(part)
        if part and not _REMINDER_META_RE.search(part):
            kept.append(part)
    sentence = _reminder_sentence("; ".join(kept))
    if len(sentence) > _RESCUE_MAX:
        sentence = _reminder_sentence(sentence[:_RESCUE_MAX].rsplit(" ", 1)[0])
    if sentence and len(sentence) >= 20 and _internal_hit(sentence) is None:
        return sentence, ("composer: reminder written as one human sentence (%d -> %d chars)"
                          % (len(text), len(sentence)))
    return _REMINDER_FALLBACK, ("composer: nothing readable survived (%d chars); "
                                "delivered as a dashboard pointer" % len(text))


def _rescue_reminder(body, to, subsystem):
    """(body, note). Rewrite an instruction-shaped reminder into a sentence; never lose it."""
    text = "" if body is None else str(body)
    if not text.strip():
        return body, None
    if subsystem in DEDUPE_EXEMPT_SUBSYSTEMS or not _owner_scope(to):
        return body, None
    if not _is_reminder_class(text):
        return body, None
    try:
        if _internal_hit(text) is None:
            return body, None
    except Exception:                                          # noqa: BLE001
        return body, None
    # ... rewrite
    work = text
    for _ in range(6):
        nxt = _RESCUE_DROP_PAREN.sub("", work)
        if nxt == work:
            break
        work = nxt
    work = _RESCUE_STRIP_PREFIX.sub("", work)
    parts = re.split(r"(?<=[.!?])\s+", " ".join(work.split()))
    kept = [p for p in parts if not _RESCUE_DROP_SENTENCE.search(p)]
    while kept and (len(" ".join(kept)) > _RESCUE_MAX or _RESCUE_DROP_SENTENCE.search(kept[-1])):
        kept.pop()
    human = " ".join(kept).strip()
    if human and human[-1] not in ".!?":
        human += "."
    human_ok = bool(human and len(human) >= 20)
    if human_ok:
        try:
            human_ok = _internal_hit(human) is None
        except Exception:                                      # noqa: BLE001
            human_ok = True
    if human_ok:
        return human, "rescue: reminder rewritten for a human (%d -> %d chars)" % (
            len(text), len(human))
    # The old sentence-by-sentence rescue could not repair a one-sentence reminder whose
    # lead was an agent instruction (the measured VS Code packet). Ask the composer that
    # writes reminders at the sender; it keeps the substance and writes one sentence.
    try:
        composed, note = compose_reminder_sentence(text)
        if composed and len(composed) >= 20 and _internal_hit(composed) is None:
            return composed, note or ("rescue: reminder rewritten for a human (%d -> %d chars)"
                                      % (len(text), len(composed)))
    except Exception:                                          # noqa: BLE001
        pass
    if not human or len(human) < 20:
        return body, "rescue: nothing readable remained; left for the guard to refuse"
    return body, ("rescue: rewritten body still reads as internal prose (%r); "
                  "left for the guard" % (_internal_hit(human)[1][:60]
                                          if _internal_hit(human) else "guard error"))

def _body_guard(body, to, subsystem):
    """(hit, notes): the first of rules 1g/1h that refuses this body, or None.

    CREDENTIAL applies to every recipient -- asking a customer for a login in a text is
    the same fault -- while INTERNAL applies to the owner only, because "internal prose"
    is a judgement about what he can read, not about a message a human drafted for
    someone else.
    """
    notes: list = []
    if subsystem in DEDUPE_EXEMPT_SUBSYSTEMS:
        return None, notes
    if _guard_on("CREDENTIAL"):
        phrase, err = _guarded("credential", credential_request, body)
        if err:
            notes.append(err)
        elif phrase:
            return {"kind": "credential", "code": CREDENTIAL_CODE, "why": phrase}, notes
    if _guard_on("INTERNAL") and _owner_scope(to):
        hit, err = _guarded("internal", _internal_hit, body)
        if err:
            notes.append(err)
        elif hit:
            cls, why = hit
            return {"kind": "internal", "code": "internal_prose:%s" % cls,
                    "cls": cls, "why": why}, notes
    return None, notes


# --------------------------------------------------------------------------
# THE FRONT DESK -- one item in, one message out
# --------------------------------------------------------------------------
#
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

# --------------------------------------------------------------------------- #
# The topic ledger — "we already told him this" (added 2026-10-19)
# --------------------------------------------------------------------------- #
# WHY. `attempt.topic` and `ask.topic` have been written since 2026-10-14 and read by
# nothing. Dedup is `policy_hash`, which is the BODY: four reminders for one payment, each
# reworded, are four different hashes and all four are allowed. Measured in his thread
# 2026-10-05/08: four texts for the same $597.29 settlement, three of them inside 90 minutes.
# `owner_topic.admit()` answers the question this relay could not ask — have we already said
# this? — and `owner_flood_guard` cannot, because it keys on the body too.
#
# IT FAILS OPEN, ALWAYS. A missing module, a missing table or a corrupt store must never
# withhold a text. The helper returns None and the relay carries on exactly as before, with
# one line on stderr so the degradation is visible rather than silent.
_TOPIC_MOD = None
_TOPIC_WARNED = False


def _topic():
    """The topic ledger module, loaded once by path. None on any failure."""
    global _TOPIC_MOD, _TOPIC_WARNED
    if _TOPIC_MOD is not None:
        return _TOPIC_MOD
    try:
        import importlib.util

        path = os.environ.get("OWNER_TOPIC_PY", "/root/bin/owner_topic.py")
        spec = importlib.util.spec_from_file_location("owner_topic", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _TOPIC_MOD = mod
        return mod
    except Exception as exc:  # noqa: BLE001 - a brake that raises is a brake that does nothing
        if not _TOPIC_WARNED:
            _TOPIC_WARNED = True
            print("owner-topic ledger unavailable (%r); topic cooldown is OFF for this run"
                  % (exc,), file=sys.stderr)
        return None


def _topic_verdict(body, topic, subsystem, now):
    """admit() or None. Read-only, and never inside the relay's write transaction."""
    mod = _topic()
    if mod is None:
        return None
    try:
        return mod.admit(body, reason=topic or "", subsystem=subsystem, topic=topic,
                         now=now, conn=None)
    except Exception:  # noqa: BLE001
        return None


def _topic_flush(body, topic, subsystem, now, verdict, reason_code):
    """Record the outcome, AFTER the relay has committed.

    Deliberately outside the transaction: a second connection writing while the relay holds
    SQLite's write lock is how `database is locked` wedges a tick on this estate. A ledger
    that fails here must cost nothing but the count.
    """
    mod = _topic()
    if mod is None:
        return
    try:
        if verdict == "SEND":
            mod.record(body, reason=topic or "", subsystem=subsystem, topic=topic, now=now)
        elif reason_code in ("topic_cooldown", "topic_closed"):
            mod.note_refusal(body, reason=topic or "", subsystem=subsystem, topic=topic, now=now)
    except Exception:  # noqa: BLE001
        pass



def _stale_verdict(body, subsystem, reason, now):
    """A deadline the body names has already passed. None when the body may go.

    Read-only and fails OPEN: an unreadable ledger must never silence a reminder that is
    still true.
    """
    mod = _topic()
    if mod is None:
        return None
    try:
        return mod.stale_reference(body, subsystem=subsystem, reason=reason, now=now)
    except Exception:  # noqa: BLE001
        return None



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

            # ---- the three guards are evaluated ONCE, here, before the chain ---------
            # The chain is one if/elif expression: it cannot both run a function and
            # carry the note when that function fails. Each helper catches its own
            # guard's exceptions, and the two calls are wrapped again so that a fault in
            # the COMBINATOR (not in a guard) also fails open instead of raising out of
            # submit() -- a guard must never be the thing that loses a message. The notes
            # are appended to the attempt row's detail after it is written.
            # A REMINDER IS REWRITTEN, NEVER DROPPED. Measured 2026-10-19: 9 of 34 distinct
            # reminder texts would otherwise be refused - the Weinberg settlement, the Fisher
            # SD-card search, the Weitman bench job. The guard is right that the body was an
            # agent instruction and wrong to make that a reason he never hears the reminder.
            # The rescued text then faces every rule below exactly as any other body does.
            body, rescue_note = _rescue_reminder(body, to, subsystem)
            got_b, err_b = _guarded("body-guards", _body_guard, body, to, subsystem)
            got_q, err_q = _guarded("quiet-guard", _quiet_guard, c, now, urgency,
                                    class_hint, to, subsystem)
            body_hit, body_notes = got_b if got_b else (None, [])
            quiet_hit, quiet_notes = got_q if got_q else (None, [])
            guard_notes = list(body_notes) + list(quiet_notes) + [
                e for e in (err_b, err_q) if e]

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

            # Rule 1g, NEVER ASK FOR A CREDENTIAL IN A TEXT (added 2026-10-19).
            # Measured, both delivered to him: 2026-10-16 14:24 "Give me the NJ Premier
            # Business Services login and I will file 06/2026 now", and the same ask with
            # a user id in the body on 2026-10-17 14:22. A login typed into a text lives
            # in a text thread for ever, and this channel is the one place it must never
            # be asked for. Rule 1g is placed with the other mutes and BEFORE the
            # duplicate rules, so a body we would never send does not burn a dedupe slot.
            elif body_hit and body_hit["kind"] == "credential":
                verdict, reason_code = "SUPPRESS", body_hit["code"]
                detail_t = ("SUPPRESS: the body asks the reader for a credential (%s) -- "
                            "%s. Two of these were delivered to him on 2026-10-16 and "
                            "2026-10-17 (attempt {aid})"
                            % (_q(body_hit["why"]), CREDENTIAL_RULE_TEXT))

            # Rule 1h, INTERNAL PROSE IS NOT A MESSAGE TO A HUMAN (added 2026-10-19).
            # Delivered to him, all of them: an instruction to an agent ("present ONE
            # numbered owner-approval ask"), a work order that names a repo path, a
            # health file in his own docs, "[Budget exceeded for : ceoreserveexhausted]",
            # "Remembered.", and one body that stopped at "the contact block you supplied
            # is". The reason code names the CLASS, so status() separates "we sent him a
            # path" from "we sent him a fragment".
            elif body_hit and body_hit["kind"] == "internal":
                verdict, reason_code = "SUPPRESS", body_hit["code"]
                detail_t = ("SUPPRESS: internal prose, not a message to a human -- class "
                            "%s, matched %s. It is an instruction to a system, a "
                            "repository path, a machine string, a bare acknowledgement or "
                            "half a sentence (attempt {aid})"
                            % (body_hit["cls"], _q(body_hit["why"])))

            # Rule 1f, QUIET HOURS (added 2026-10-19). 112 of 548 delivered outbound
            # texts (20.4%) arrived between 23:00 and 07:00 his time, including reminders
            # at 02:29, 02:55 and 03:09. Placed after the body guards on purpose: when
            # BOTH apply -- internal prose at 02:29 -- the recorded reason should be the
            # one that would still be true at 11:00, not the one that expires by itself.
            elif quiet_hit:
                verdict, reason_code = "SUPPRESS", "quiet_hours"
                detail_t = ("SUPPRESS: %s. Dropped, NOT queued: every sender on this "
                            "channel is periodic and will re-fire at an hour he is awake, "
                            "and a queue would hand him the whole night's traffic at once "
                            "(attempt {aid})" % quiet_hit["why"])

            # Rule 2b, the ceiling.  Evaluated AFTER the kill switch and BEFORE the
            # duplicate rules: a text that will never be sent must not burn a dedupe
            # slot.  A door that fits first (relay.fit) can never hit this; a refusal
            # here is the honest record of a caller that skipped the fit.
            # Rule 1d, the TOPIC LEDGER (added 2026-10-19). Placed after the standing-rule
            # mutes and before the ceiling/duplicate rules because it is a fact about the
            # conversation, not about this body: "we already told him about this payment".
            # A refusal here is `topic_cooldown` (later) or `topic_closed` (not until something
            # changes) -- two different sentences, never one.
            elif (tv := _topic_verdict(body, topic, subsystem, now)) is not None and not tv["allow"]:
                verdict, reason_code = "SUPPRESS", str(tv["code"])
                detail_t = "SUPPRESS: %s (attempt {aid})" % (tv["detail"],)

            # Rule 1e, STILL TRUE? (added 2026-10-19). A reminder fires because it is DUE;
            # nothing asked whether it is still TRUE. Measured in his thread: "PayPal case
            # ... seller response deadline is Oct 7, 2026" was delivered on 2026-10-08, a day
            # after the deadline it names. Topic identity cannot catch it -- the amount has
            # never been said, so it is a first message on a fresh topic -- and no
            # body-shaped rule can see a date. Only reminder/alert families are judged.
            elif (sv := _stale_verdict(body, subsystem, reason, now)) is not None:
                verdict, reason_code = "SUPPRESS", str(sv["code"])
                detail_t = "SUPPRESS: %s (attempt {aid})" % (sv["detail"],)

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
                # 2026-10-18: the ceiling is now `ceiling_for(to)`. The owner's rule is
                # about HIS reading, so a third-party recipient gets Twilio's 1600. Before
                # this, a 377-char message he asked us to send to someone else was
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
            if guard_notes:
                # A guard that could not be evaluated still records what it could not do:
                # "fail open" may not mean "fail silently" (the measurement rule).
                detail = detail + " | " + " ; ".join(guard_notes)
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

    _topic_flush(body, topic, subsystem, now, verdict, reason_code)

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
        "guard_notes": guard_notes,
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
            # An INBOUND row is not a verdict -- it is the other direction of the
            # conversation (see `record_inbound`), so it is counted on its own below and
            # kept out of the verdict table, which must mean what its name says.
            out = {v: 0 for v in VERDICTS}
            for r in c.execute(
                "SELECT verdict, COUNT(*) AS n FROM attempt WHERE at >= ? AND verdict != ? "
                "GROUP BY verdict", (cut, INBOUND_VERDICT)
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

        total = int(c.execute("SELECT COUNT(*) AS n FROM attempt WHERE verdict != ?",
                              (INBOUND_VERDICT,)).fetchone()["n"])
        inbound = {
            "total": int(c.execute("SELECT COUNT(*) AS n FROM attempt WHERE verdict = ?",
                                   (INBOUND_VERDICT,)).fetchone()["n"]),
            "24h": int(c.execute(
                "SELECT COUNT(*) AS n FROM attempt WHERE verdict = ? AND at >= ?",
                (INBOUND_VERDICT, cut24)).fetchone()["n"]),
        }
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
            "inbound": inbound,
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

        try:
            # Rule 1f's second bypass is only real if the inbound door WRITES this marker.
            # A zero here is not a fault in this module: it is the answer to "is the
            # awake bypass wired?", which cannot be seen from the code that reads it.
            n_in = int(conn_.execute(
                "SELECT COUNT(*) AS n FROM attempt WHERE verdict = ?",
                (INBOUND_VERDICT,)).fetchone()["n"])
            newest = conn_.execute(
                "SELECT MAX(at) AS ts FROM attempt WHERE verdict = ?",
                (INBOUND_VERDICT,)).fetchone()["ts"]
            add("inbound-marker", True,
                "%d inbound row(s) via record_inbound(), newest %s -- quiet hours opens "
                "when one is newer than %g min; a door that does not record his inbound "
                "text cannot be seen by rule 1f" % (n_in, newest or "never",
                                                    _awake_minutes()[0]))
        except Exception as exc:                                # noqa: BLE001
            add("inbound-marker", False, "%s: %s" % (type(exc).__name__, exc))

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
        "MAX_CHARS = %d (OWNER_TEXT_MAX_CHARS, then legacy "
        "OWNER_TEXT_RELAY_MAX_CHARS) -> submit() returns TOO_LONG over this and fit() "
        "cuts to it; NO COALESCER EXISTS, so verdict COALESCE is retained only to read "
        "rows written before the rule was withdrawn" % (MAX_CHARS,))
    add("dedupe-key", True,
        "policy_hash = sha256(normalise(body) [+ '\\n' + dedupe_extra]); the DOOR and the "
        "SUBSYSTEM are NOT in the key, and rules 3/3b filter on body_hash alone -- so an "
        "identical body from one door dedupes against the same body from another. Read "
        "before changing anything (2026-10-19): there was no door-shaped component to "
        "remove, and the 6-hour window and the dedupe_extra contract are untouched")

    qstart, qend, qprob = _quiet_window()
    aw_min, aw_prob = _awake_minutes()
    try:
        qinside, qwhy = quiet_hours_now(_now())
    except Exception as exc:                                    # noqa: BLE001
        qinside, qwhy = None, "raised %s: %s" % (type(exc).__name__, exc)
    add("guard-quiet", qinside is not None,
        "%s=%r -> %s; window %s; awake bypass %g min%s; %s"
        % (GUARD_ENV["QUIET"], os.environ.get(GUARD_ENV["QUIET"]),
           "ON" if _guard_on("QUIET") else "OFF by env",
           ("%02d:%02d-%02d:%02d" % (qstart // 60, qstart % 60, qend // 60, qend % 60))
           if qstart is not None and qend is not None else "UNPARSABLE (%s)" % qprob,
           aw_min, (" (%s)" % aw_prob) if aw_prob else "",
           ("INSIDE now: " if qinside else "outside now: ") + str(qwhy)))
    add("guard-credential", True,
        "%s=%r -> %s; needs a credential noun AND a request verb before it in the same "
        "sentence, so a status report stays a message; %s; applies to every recipient"
        % (GUARD_ENV["CREDENTIAL"], os.environ.get(GUARD_ENV["CREDENTIAL"]),
           "ON" if _guard_on("CREDENTIAL") else "OFF by env", CREDENTIAL_RULE_TEXT))
    add("guard-internal", True,
        "%s=%r -> %s; classes path, instruction, machine, addressed, ack, truncated; "
        "reason code is internal_prose:<class>; owner recipients only, and never a "
        "safety-critical subsystem"
        % (GUARD_ENV["INTERNAL"], os.environ.get(GUARD_ENV["INTERNAL"]),
           "ON" if _guard_on("INTERNAL") else "OFF by env"))
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
