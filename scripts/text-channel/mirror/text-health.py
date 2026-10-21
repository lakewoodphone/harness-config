#!/usr/bin/env python3
"""text-health: does the owner-text system hold its own invariants?

Read-only. One line per invariant; every FAIL carries the evidence that proves it.
Exit 1 when anything fails, so it can be a cron or a deploy gate. Written
2026-09-30 because every defect found in this system was invisible from any single
tool: the daily ceiling read 20 in the settings, 8 in the flood-guard constant and
3 in the text the owner actually saw; and a model id could be named in a request,
answered with HTTP 200, and never be the model that served it.

The date trap this script had to fix in itself, and why it carries a parser:
`inbox.db.messages.date_sent` holds TWO formats -- RFC 2822
("Wed, 30 Sep 2026 14:16:59 +0000", written by textsend) and ISO 8601
("2026-09-30T14:16:57+00:00", written by the mirror). Comparing either against an
ISO string with `>=` sorts them as text and silently undercounts: the first
version of this check reported 258 rows where the truth was 118, and 49
"duplicates" that were really repeats spread across weeks rather than a flood.

THE SECOND FALSE GREEN, closed 2026-10-02, and it is the same shape one level down:

  E1 printed `OK  no body reaches the owner twice inside 30 min, in the last 24 h
  -> 0 repeat(s) in 24 h` at 2026-10-02T00:56Z, while `sms_log` held 911 outbound rows
  to the owner dated 2026-10-01 with `status='suppressed'` and no `twilio_sid`, 908 of
  them two bodies refused every ~60 s for seven hours:

    select count(*) from sms_log where to_number like '%8483897895%'
      and direction='outbound' and created_at >= '2026-10-01'
      and created_at < '2026-10-02';                            -- 925
    ... and status='suppressed'                                 -- 911
    ... and (twilio_sid is null or twilio_sid='')               -- 911

  E1 read `inbox.db.messages`, which holds only what this channel WROTE, and every row
  in it is delivered. A `suppressed` row is an attempt nobody looks at, so an attempt
  nobody counted. E1 and E2 now count ATTEMPTS per (recipient, body-hash) from BOTH
  ledgers -- the channel's own `send_attempt` table in `inbox.db` and the app's
  `sms_log`, every status -- through `owner_flood_guard.py`, and fail at that module's
  own breaker threshold rather than at a number repeated here.

  (The two ledgers must not be compared as strings. `created_at >= datetime('now','-1
  hour')` selects 927 rows on this data, not the last hour: ISO stamps carry a 'T'
  (0x54) where SQLite's datetime() writes a space (0x20), so every ISO stamp sorts
  above it. That is where the number 927 in the incident record comes from -- it is
  everything from 2026-10-01T00:00Z onward, not the last hour. `owner_flood_guard.
  parse_stamp` parses instead of comparing.)
"""
from __future__ import annotations

import email.utils
import importlib.util
import json
import os
import re
import sqlite3
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

#: The three trees this instrument reads. Resolved from HOME so the same file runs on
#: the office authority (/home/zabz) and on the cloud authority (root, where
#: /home/zabz/{bin,.sms-inbox,personal-secretary-mvp} are symlinks into /root and
#: /opt/company). Overridable so a throwaway copy can be pointed at a fixture.
APP = Path(os.environ.get("AITEXT_APP") or (Path.home() / "personal-secretary-mvp"))
BIN = Path(os.environ.get("AITEXT_BIN") or (Path.home() / "bin"))
HERE = Path(__file__).resolve().parent
SMS = Path(os.environ.get("AITEXT_SMS_DIR") or (Path.home() / ".sms-inbox"))
OWNER = "+18483897895"
GATEWAY = "http://127.0.0.1:8002"
WINDOW_DAYS = 7
DUPLICATE_WINDOW_MINUTES = 30   # a repeat inside this is a flood, not a reminder


def _resolve_app_db() -> Path:
    """The app's OWN database, resolved the way the app resolves it, not a fixed path.

    THE FALSE GREEN THIS FIXES (measured 2026-10-13, the secratary-cloud cutover):
    this file named ``<app>/data/secretary.db`` because that is where the office
    authority kept it. On the cloud authority the app's `.env` says
    ``DATABASE_URL=sqlite:////root/authority.db``, and ``<app>/data/secretary.db``
    is a 1.8 MB leftover with no ``owner_text_decision`` table at all. D2 failed
    with ``no such table``, but E1/E2/F1 read that empty copy and printed a green
    reading -- an instrument that reports health off the wrong store is exactly
    the false green its own header is about. So the path comes from the
    environment or the app's `.env` first (the app's own single source of truth),
    and the old default is only a fallback.
    """
    raw = str(os.environ.get("DATABASE_URL") or "").strip()
    if not raw:
        try:
            for line in (APP / ".env").read_text(
                    encoding="utf-8", errors="replace").splitlines():
                line = line.strip()
                if line.startswith("DATABASE_URL="):
                    raw = line.split("=", 1)[1].strip()
                    break
        except OSError:
            raw = ""
    for prefix in ("sqlite:///", "sqlite://", "file:"):
        if raw.startswith(prefix):
            raw = raw[len(prefix):]
            break
    if raw:
        return Path(raw.split("?")[0])
    return APP / "data" / "secretary.db"


APP_DB = _resolve_app_db()
#: The owner's personal iPhone, the number every owner text is judged against.
OWNER_NUMBER = os.environ.get("OWNER_PHONE_NUMBER", "+18483897895")

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, evidence: str) -> None:
    results.append((name, bool(ok), evidence))


def load_guard():
    """The flood brake's module: the deployed one first, then this file's sibling.

    Resolved by path and not by import, because the module is `owner_flood_guard.py`
    next to this script in the repo and in `~/bin` after a deploy, and the instrument
    has to work in both places -- an instrument that only runs from the deployed tree
    is one that cannot be tested before it is trusted.
    """
    for path in (BIN / "owner_flood_guard.py", HERE / "owner_flood_guard.py"):
        if not path.exists():
            continue
        try:
            spec = importlib.util.spec_from_file_location("owner_flood_guard", str(path))
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            module.__loaded_from__ = str(path)
            return module
        except Exception:
            continue
    return None


def ro(path) -> sqlite3.Connection:
    return sqlite3.connect("file:%s?mode=ro" % path, uri=True)


def parse_when(value):
    """Parse BOTH timestamp formats the stores use. Aware datetime, or None."""
    if not value:
        return None
    text = str(value).strip()
    try:
        got = email.utils.parsedate_to_datetime(text)
        if got is not None:
            return got if got.tzinfo else got.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        pass
    try:
        got = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return got if got.tzinfo else got.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def norm_body(body) -> str:
    """The historical 160-character normalisation, kept as the reference.

    The live rule is `owner_flood_guard.normalise`, and C2 asserts the two still agree
    on samples: if they drift, the brake counts one message as two and this instrument
    counts two as one, and both would be quietly wrong in opposite directions.
    """
    text = re.sub(r"[^a-z0-9 ]", " ", str(body or "").lower())
    return " ".join(text.split())[:160]


#: Bodies the C2 agreement check uses: punctuation, case, run-together whitespace and a
#: message over 160 characters, which is where two normalisations actually diverge.
IDENTITY_SAMPLES = (
    "CALL TOPGOLF EDISON GUEST CARE, (732) 374-4097 - reservation!",
    "call   topgolf edison guest care, (732) 374-4097 - reservation!",
    "Check 300DDR for Fishman tickets 74114 (1TB, open-cover fee) and call the shop "
    "back about the deposit before Friday, 2026-10-02, or the parts get restocked",
)


# ── A. ONE GATEWAY, ONE ALIAS SET, A CATALOGUE THAT AGREES WITH IT ──────────
live: list = []
try:
    live = [m.get("id") for m in json.loads(
        urllib.request.urlopen(GATEWAY + "/v1/models", timeout=20).read())["data"]]
    aliases = sorted(str(m) for m in live if str(m).startswith("secretary-"))
    check("A1 the gateway catalogue is reachable", bool(live),
          "GET /v1/models -> %d ids" % len(live))
    check("A2 the route aliases exist", bool(aliases), "aliases=%s" % aliases)
    cached = json.loads((SMS / "model-catalog.json").read_text())["ids"]
    # A CACHE IS LARGER THAN THE CATALOGUE WHEN THE CATALOGUE SHRANK, and on 2026-10-21
    # that was the whole of A3's red: the gateway excluded Google (33 -> 26 ids) while
    # textdecide's cache still held the seven Google ids from before the change.  The old
    # evidence printed only `missing_from_cache=[]`, which is true and reads like a
    # contradiction.  Name both directions; the check still fails on either, because a
    # stale extra can be selected and a missing live id cannot be.
    missing = sorted(set(live) - set(cached))
    stale = sorted(set(cached) - set(live))
    check("A3 the responder cache matches the live catalogue",
          not missing and not stale,
          "cache=%d live=%d missing_from_cache=%s stale_in_cache=%s"
          % (len(cached), len(live), missing[:6], stale[:6]))
except Exception as exc:
    check("A1 the gateway catalogue is reachable", False, "%s: %s" % (type(exc).__name__, exc))

# ── B. A NAMED MODEL MUST BE THE MODEL THAT SERVES ──────────────────────────
try:
    cfg = (APP / "app" / "config.py").read_text()
    tiers = re.findall(r'model_tier\d:\s*str\s*=\s*"([^"]+)"', cfg)
    missing = [t for t in tiers if t not in live]
    check("B1 every configured app model tier is listed in the catalogue",
          bool(tiers) and not missing,
          "tiers=%s not_listed=%s" % (tiers, missing or "none"))
except Exception as exc:
    check("B1 every configured app model tier is listed in the catalogue", False, str(exc))

try:
    gateway = (APP / "app" / "services" / "ai_gateway.py").read_text()
    # Adjacent string literals in source concatenate at runtime, but their quotes
    # stay in the file: flatten them to nothing so a phrase spanning a line break
    # is still found. (The first version of this check failed on exactly that, and
    # reported a working fix as broken.)
    flat = " ".join(gateway.replace('"', " ").replace("'", " ").split())
    has_table = "_LEGACY_SHORT_MODEL_IDS" in gateway
    check("B2 the gateway resolves short ids instead of silently rerouting",
          has_table, "ai_gateway._LEGACY_SHORT_MODEL_IDS present=%s" % has_table)
    loud = "serving it on the default route" in flat
    check("B3 an unresolvable model id is no longer silent", loud,
          "an unresolved id is logged and served on the settings' own default route, instead "
          "of running on whichever model smart routing happened to pick for the task")
except Exception as exc:
    check("B2 the gateway resolves short ids instead of silently rerouting", False, str(exc))

# ── C. ONE CEILING PER CONCEPT ──────────────────────────────────────────────
try:
    fg = (APP / "app" / "services" / "owner_sms_flood_guard.py").read_text()
    # The ceiling is now resolved from the setting rather than hardcoded, so accept
    # either form: a literal, or an assignment from the env helper. What is NOT
    # acceptable is a literal that disagrees with the setting.
    lit = re.search(r"^OWNER_SMS_DAILY_CEILING\s*=\s*(\d+)", fg, re.M)
    from_env = re.search(r"^OWNER_SMS_DAILY_CEILING\s*=\s*_daily_ceiling_from_env\(", fg, re.M)
    doc = re.search(r"OWNER_SMS_DAILY_CEILING = (\d+)", fg)
    docv = int(doc.group(1)) if doc else None
    env = ""
    for line in (APP / ".env").read_text().splitlines():
        if line.startswith("OWNER_SMS_DAILY_QUOTA="):
            env = line.split("=", 1)[1].strip()
    conf = re.search(r"owner_sms_daily_quota:\s*int\s*=\s*(\d+)",
                     (APP / "app" / "config.py").read_text())
    confv = int(conf.group(1)) if conf else None
    if from_env:
        ok = docv is not None and env != "" and docv == int(env) == confv
        form = "read from OWNER_SMS_DAILY_QUOTA (single source of truth)"
    elif lit:
        ok = int(lit.group(1)) == int(env or -1) == confv
        form = "hardcoded literal %s" % lit.group(1)
    else:
        ok, form = False, "no OWNER_SMS_DAILY_CEILING assignment found"
    check("C1 the autonomous owner-SMS ceiling is one number everywhere", ok,
          "%s; docstring=%s .env OWNER_SMS_DAILY_QUOTA=%s config default=%s"
          % (form, docv, env or "(unset)", confv))
except Exception as exc:
    check("C1 the autonomous owner-SMS ceiling is one number everywhere", False, str(exc))

# ── C2. THE BRAKE MUST EXIST AND BE WIRED IN, OR E1 IS DECORATION ───────────
# A counter with nothing that acts on it is an instrument that reports a flood while
# the flood continues. This is the check that makes E1 mean something: the module that
# owns the threshold is deployed, and the sender actually consults it.
try:
    guard = load_guard()
    if guard is None:
        check("C2 the flood brake is deployed and wired into the sender", False,
              "owner_flood_guard.py was found in neither %s nor %s: nothing counts "
              "identical attempts, so nothing stops them" % (BIN, HERE))
    else:
        looked, wired, missing = [], [], []
        for src_path in (BIN / "textsend.py", HERE / "textsend.py"):
            if not src_path.exists():
                missing.append(str(src_path))
                continue
            src = src_path.read_text(encoding="utf-8", errors="replace")
            looked.append(str(src_path))
            if "_flood_verdict(" in src and "_flood_note(" in src and "fit_owner_body(" in src:
                wired.append(str(src_path))
        # The two definitions of "the same message" must agree, or the brake and this
        # instrument count different things while both look right.
        disagreements = [s[:40] for s in IDENTITY_SAMPLES if guard.normalise(s) != norm_body(s)]
        check("C2 the flood brake is deployed and wired into the sender",
              bool(wired) and not disagreements,
              "guard=%s threshold=%d identical attempts / %d min; sender wired in %s%s%s"
              % (getattr(guard, "__loaded_from__", "?"),
                 guard.BREAKER_ATTEMPTS_PER_HOUR, guard.ATTEMPT_WINDOW_MINUTES,
                 wired or "NOTHING", ("; checked %s" % ", ".join(looked)) if looked else "",
                 "; identity DISAGREES on %s" % disagreements if disagreements else
                 "; body identity agrees on %d sample(s)" % len(IDENTITY_SAMPLES)))
except Exception as exc:
    check("C2 the flood brake is deployed and wired into the sender", False,
          "%s: %s" % (type(exc).__name__, exc))

# ── D. ONE CONVERSATION: the turn ledger must bind every send path ──────────
try:
    src = ((BIN / "sms-responder.py").read_text()
           + (BIN / "textsend.py").read_text()
           + (BIN / "textwork.py").read_text())
    honours = [m for m in ("owner_text", "record_outbound", "open_turn", "gate(")
               if m in src]
    check("D1 the text responder obeys the owner turn ledger", bool(honours),
          "references in sms-responder/textsend/textwork: %s"
          % (honours or "NONE -- the responder sends through textsend's own Twilio path, so a "
             "question IT is waiting on does not block the app, and a question the APP is "
             "waiting on does not block it"))
except Exception as exc:
    check("D1 the text responder obeys the owner turn ledger", False, str(exc))

try:
    c = ro(APP_DB)
    turns = list(c.execute(
        "select id, sent_at, answered_at from owner_text_turn order by id desc limit 20"))
    sends = list(c.execute(
        "select id, allowed, code from owner_text_decision order by id desc limit 50"))
    allowed = [s for s in sends if s[1]]
    check("D2 the gate records every decision it makes",
          bool(sends) and bool(turns),
          "%d recent turns, %d recent decisions (%d allowed, %d refused)"
          % (len(turns), len(sends), len(allowed), len(sends) - len(allowed)))
except Exception as exc:
    check("D2 the gate records every decision it makes", False, str(exc))

# ── E. TOO MUCH: ATTEMPTS, not deliveries ───────────────────────────────────
#
# THE FALSE GREEN THIS REPLACES. Until 2026-10-02 this check read
# `inbox.db.messages` -- a store that holds only what went OUT -- and counted repeat
# DELIVERIES inside 30 minutes. On 2026-10-01 it printed OK while 911 `suppressed`
# rows were written to `sms_log` for the owner, 908 of them two bodies refused every
# ~60 s for seven hours. A suppressed row is not a failed send; it is a send nobody
# looks at, so it has to be counted as an attempt or the instrument is lying by
# construction.
try:
    guard = load_guard()
    if guard is None:
        raise RuntimeError("owner_flood_guard.py is not deployed, so attempts cannot be counted")
    now = datetime.now(timezone.utc)
    chan = ro(SMS / "inbox.db") if (SMS / "inbox.db").exists() else None
    appc = ro(APP_DB) if APP_DB.exists() else None
    if appc is None:
        raise RuntimeError("the attempt ledger %s is unreadable, so this check has "
                           "nothing to count and will not claim health" % APP_DB)

    threshold = int(guard.BREAKER_ATTEMPTS_PER_HOUR)
    hour = guard.attempts_report(guard.ATTEMPT_WINDOW_MINUTES / 60.0, conn=chan,
                                 app_conn=appc, now=now)
    worst_hour = hour[0] if hour else None
    hot = [r for r in hour if r["attempts"] >= threshold]
    if worst_hour:
        ev = ("worst: %d attempt(s) of %r between %s and %s (channel=%d app=%d "
              "refused=%d delivered=%d); %d group(s) at or above the threshold of %d"
              % (worst_hour["attempts"], worst_hour["body_head"][:60], worst_hour["first"],
                 worst_hour["last"], worst_hour["channel"], worst_hour["app"],
                 worst_hour["refused"], worst_hour["delivered"], len(hot), threshold))
    else:
        ev = "no outbound attempt to any recipient in the last %d min" % guard.ATTEMPT_WINDOW_MINUTES
    check("E1 no (recipient, body) is ATTEMPTED %d times or more inside %d min "
          "(attempts, not deliveries)" % (threshold, guard.ATTEMPT_WINDOW_MINUTES),
          not hot, ev)
except Exception as exc:
    check("E1 no (recipient, body) is attempted repeatedly inside the breaker window",
          False, "%s: %s" % (type(exc).__name__, exc))

# E2 -- THE 24-HOUR VIEW, which is the one that catches a loop that never crossed the
# hourly threshold because it was slow. The invariant is not "few attempts" (a real
# obligation may legitimately be retried across a day) but "an attempt that never once
# reached him": a body tried N or more times in a day with ZERO deliveries is the
# 2026-10-01 shape exactly -- 911 attempts, 0 deliveries, and nothing anywhere said so.
#
# AND IT IS STILL ARRIVING THAT MAKES IT A FAILURE. Measured 2026-10-02T03:05Z on this
# data: E2 read 801 attempts in 24 h with 783 refused and named one body attempted 487
# times with zero deliveries, whose last attempt was 2026-10-01T14:02Z -- twelve hours
# before the reading. That group IS the incident, and the incident is over. A check that
# stays red for the rest of the day after a loop stops is the other half of the
# false-green problem: it trains the reader to skip the line. So the failure condition is
# "the last attempt is inside the breaker window -- it is still arriving", and a group that
# has stopped is carried in the evidence with its last attempt named, where it belongs.
try:
    guard = load_guard()
    if guard is None:
        raise RuntimeError("owner_flood_guard.py is not deployed")
    now = datetime.now(timezone.utc)
    chan = ro(SMS / "inbox.db") if (SMS / "inbox.db").exists() else None
    appc = ro(APP_DB)
    day = guard.attempts_report(24.0, conn=chan, app_conn=appc, now=now)
    threshold = int(guard.BREAKER_ATTEMPTS_PER_HOUR)
    still_cut = now - timedelta(minutes=int(guard.ATTEMPT_WINDOW_MINUTES))
    silent = [r for r in day if r["attempts"] >= threshold and r["delivered"] == 0]
    live_groups, stopped = [], []
    for r in silent:
        moment = parse_when(r["last"])
        (live_groups if (moment and moment >= still_cut) else stopped).append(r)
    attempted = sum(r["attempts"] for r in day)
    refused = sum(r["refused"] for r in day)
    worst = (live_groups or stopped or day or [None])[0]
    evidence = ("%d attempt(s) in 24 h, %d of them refused; %d body/bodies tried %d+ "
                "times with ZERO deliveries, %d of them still arriving inside the last "
                "%d min%s"
                % (attempted, refused, len(silent), threshold, len(live_groups),
                   int(guard.ATTEMPT_WINDOW_MINUTES),
                   ("; %d stopped, worst: %d attempt(s) of %r, refused=%d, last %s -- "
                    "stopped, so this is the incident's history, not a live loop"
                    % (len(stopped), worst["attempts"], worst["body_head"][:60],
                       worst["refused"], worst["last"])) if worst else ""))
    check("E2 no body is STILL attempted %d+ times in 24 h without one delivery" % threshold,
          not live_groups, evidence)
except Exception as exc:
    check("E2 no body is attempted repeatedly in 24 h without one delivery", False,
          "%s: %s" % (type(exc).__name__, exc))

# ── F. TOO LITTLE: nothing autonomous may rot in the queue ──────────────────
#
# THE SECOND NUMBER THIS CHECK HAD TO STOP CARRYING (2026-10-13). F1 said "more than
# 24 h" while `app/services/lifecycle_sweep.py` -- the module that actually ages the
# table -- keeps a held row for 336 h at reason `urgent_email`, 168 h for an owner
# question, 168 h by default and 24 h for a reminder. A held money/email notice three
# days old is WITHIN the app's stated shelf life, not rot, and a hardcoded 24 called
# it a fault. So the horizon is read from the module that owns it, exactly as C1 reads
# the SMS ceiling, and the check fails only when a row is past ITS OWN shelf life.
try:
    _horizon = None
    try:
        _ls = APP / "app" / "services" / "lifecycle_sweep.py"
        _spec = importlib.util.spec_from_file_location("_th_lifecycle", str(_ls))
        _mod = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_mod)
        _horizon = _mod._owner_message_horizon_hours
    except Exception as _hx:  # noqa: BLE001 - an unreadable policy is not health
        _horizon = None

    def _shelf_life(reason) -> float:
        return float(_horizon(reason)) if _horizon is not None else 24.0

    c = ro(APP_DB)
    rows = list(c.execute(
        "select id, created_at, last_seen_at, urgency, reason from owner_message_queue "
        "where status in ('held','queued')"))
    now = datetime.now(timezone.utc)
    stale = []
    for i, when, last_seen, urgency, reason in rows:
        moment = parse_when(last_seen) or parse_when(when)
        if moment and (now - moment) > timedelta(hours=_shelf_life(reason)):
            stale.append((i, str(when)[:10], _shelf_life(reason), urgency, reason))
    check("F1 nothing autonomous sits unsent past its own shelf life",
          not stale,
          "%d held/queued, %d past the app's own horizon%s"
          % (len(rows), len(stale),
             (" -- " + str(stale[:4])) if stale else
             (" (horizons read from app/services/lifecycle_sweep.py: urgent_email=%g h, "
              "ask_owner=%g h, reminder=%g h, default=%g h)"
              % (_shelf_life("urgent_email"), _shelf_life("ask_owner"),
                 _shelf_life("reminder:x"), _shelf_life("unspecified")))))
except Exception as exc:
    check("F1 nothing autonomous sits unsent past its own shelf life", False, str(exc))

# ── G. THE PLAIN FACTS: is the channel alive both ways ─────────────────────
try:
    cutoff = datetime.now(timezone.utc) - timedelta(days=WINDOW_DAYS)
    inbound = outbound = 0
    for direction, when in ro(SMS / "inbox.db").execute(
            "select direction, date_sent from messages where from_number=? or to_number=?",
            (OWNER, OWNER)):
        moment = parse_when(when)
        if moment and moment >= cutoff:
            if direction == "inbound":
                inbound += 1
            else:
                outbound += 1
    check("G1 the channel is alive in both directions",
          inbound > 0 and outbound > 0,
          "last %d days: %d from him, %d to him" % (WINDOW_DAYS, inbound, outbound))
except Exception as exc:
    check("G1 the channel is alive in both directions", False, str(exc))

# ── I. HIS OWN THREAD, SEEN FROM THE OTHER SIDE ─────────────────────────────
# Owner, 2026-09-30 16:13Z, after being told nothing: *"you should be able to see your
# own text thread and what you texted me and why."*
#
# The read the brain is actually given is the last line of its brief --
#     Full thread with him: python3 ~/bin/sms-inbox.py show +18483897895
# -- and this check runs THAT instrument's own query verbatim (`sms-inbox.py:cmd_show`,
# norm() = the last ten digits, matched against BOTH number columns) and requires the AI
# line's own OUTBOUND rows to come back, carrying a reason. Two things have to be true for
# him to be answered at all: the sender has to WRITE its outbound into the store
# (`textsend._record_send`, `send-from-ai-line.py`), and the read has to RETURN them.
# Checked rather than believed, because the failure mode is silent: a thread read that
# shows only his half looks exactly like a thread in which we never said anything.
try:
    conn = ro(SMS / "inbox.db")
    q = re.sub(r"\D", "", OWNER)[-10:]
    rows = conn.execute(
        "select direction, date_sent, body, coalesce(reason,'') from messages "
        "where from_number like ? or to_number like ?",
        ("%" + q + "%", "%" + q + "%")).fetchall()
    out = [(w, b, r) for d, w, b, r in rows if d == "outbound"]
    recent = [x for x in out
              if (parse_when(x[0]) or datetime(1970, 1, 1, tzinfo=timezone.utc))
              >= datetime.now(timezone.utc) - timedelta(days=WINDOW_DAYS)]
    with_reason = [x for x in out if str(x[2] or "").strip()]
    # NEWEST IS COMPUTED, NOT TAKEN FROM THE ROW ORDER. This store mixes RFC-2822 stamps
    # from Twilio with ISO ones from the sender, so neither the table order nor
    # `ORDER BY date_sent` is chronological -- the first version of this evidence line
    # called the last row returned "newest" and named 2026-10-02T00:02:41Z, while the true
    # newest outbound is 2026-09-30T16:44:20Z. A label is a claim; parse it or drop it.
    stamped = [(parse_when(w), w) for w, _b, _r in out]
    newest = max([s for s in stamped if s[0]], default=(None, ""), key=lambda s: s[0])
    check("I1 the brain can read the AI line's own OUTBOUND texts to the owner",
          bool(out) and bool(with_reason),
          "%d message(s) match his number, %d of them outbound (%d in the last %d days), "
          "%d carrying a reason -- the query is sms-inbox.py show's own%s"
          % (len(rows), len(out), len(recent), WINDOW_DAYS, len(with_reason),
             ("; newest outbound %s" % newest[1]) if out else "; NOTHING OUTBOUND IS "
             "READABLE, so the brain cannot see what it texted him or why"))
except Exception as exc:
    check("I1 the brain can read the AI line's own OUTBOUND texts to the owner", False,
          "%s: %s" % (type(exc).__name__, exc))


# ---------------------------------------------------------------------------------------
# J1: the vocabulary the channel LEARNS must be a vocabulary the ledger can FILE.
#
# Measured 2026-10-19: 10 of 11 learned aliases were unfilable - "personal" and "unknown" are
# not categories in the ledger, and a category that does not resolve to an id files nothing.
# The charge stays uncategorised, the resolver still calls it answered, and the same question
# comes back weeks later. That is the loop this invariant exists to break.
#
# An alias with NO category is not a failure: that is the documented `known_only` case - the
# vendor is known, nobody has said what the charge was for, and the rung must report it as a
# question rather than as a resolution.
# ---------------------------------------------------------------------------------------
try:
    aliases_db = BIN / ".." / ".cfo-asks" / "aliases.db"
    aliases_db = Path(os.path.expanduser(os.environ.get("CFO_ALIAS_DB", "~/.cfo-asks/aliases.db")))
    acct_db = Path(os.environ.get("CFO_ACCOUNTING_DB", "/root/accounting-data/live/accounting.db"))
    if not aliases_db.exists():
        check("J1 every learned alias names a category the ledger can file", True,
              "no alias store at %s yet - nothing has been learned" % aliases_db)
    elif not acct_db.exists():
        check("J1 every learned alias names a category the ledger can file", True,
              "NOT MEASURED: accounting db absent at %s" % acct_db)
    else:
        _a = ro(acct_db)
        try:
            known = {(r[0] or "").lower() for r in _a.execute("select name from categories")}
        finally:
            _a.close()
        _s = ro(aliases_db)
        try:
            # `ro()` does not set a row_factory, so a row is a TUPLE and `dict(r)` raises
            # "dictionary update sequence element #0 has length 9". Name the columns here
            # rather than assuming a mapping: a check that crashes reports the same FAIL as a
            # check that found something, and the two must never look alike.
            rows = [{"merchant_key": r[0], "category": r[1], "learned_at": r[2]}
                    for r in _s.execute(
                        "select merchant_key, category, learned_at from alias")]
        finally:
            _s.close()
        bad = [r for r in rows
               if str(r.get("category") or "").strip()
               and str(r["category"]).strip().lower() not in known]
        blank = [r for r in rows if not str(r.get("category") or "").strip()]
        # A GATE THAT IS ALWAYS RED IS NOT A GATE. The backlog is reported in every run; only a
        # REGRESSION - something learned inside the window that cannot be filed - fails it.
        # Otherwise every later session learns to ignore a red instrument, which is how a real
        # regression gets waved through a deploy.
        _cut = datetime.now(timezone.utc) - timedelta(days=int(
            os.environ.get("ALIAS_FILABLE_WINDOW_DAYS", "1") or 7))
        recent_bad = []
        for r in bad:
            when = parse_when(r.get("learned_at"))
            if when is None or when >= _cut:
                recent_bad.append(r)
        detail = ("%d learned alias(es); %d name a category the ledger does NOT hold and can "
                  "never be filed; %d carry no category (the known-only case, correct); "
                  "%d of the bad ones were learned in the last %s days"
                  % (len(rows), len(bad), len(blank), len(recent_bad),
                     os.environ.get("ALIAS_FILABLE_WINDOW_DAYS", "1")))
        if bad:
            detail += " :: historical backlog: " + "; ".join(
                "%s -> %r (%s)" % (str(r["merchant_key"])[:28],
                                   str(r["category"])[:16],
                                   str(r.get("learned_at"))[:10])
                for r in bad[:8])
        if recent_bad:
            detail += " :: REGRESSION (cannot be filed): " + "; ".join(
                "%s -> %r" % (str(r["merchant_key"])[:28], str(r["category"])[:16])
                for r in recent_bad[:6])
        check("J1 a newly learned alias always names a category the ledger can file",
              not recent_bad, detail)
except Exception as exc:
    check("J1 every learned alias names a category the ledger can file", False,
          "%s: %s" % (type(exc).__name__, exc))


# ---------------------------------------------------------------------------------------
# K1: "sent" in the queue must mean a text left.
#
# Measured 2026-10-19: 353 queue rows for one body in status `sent` with no sms_log row within
# thirty minutes of any sampled claim. The live path was already fixed (those occurrences are now
# `dismissed` with "machine-facing: a comms pipeline..."), so the backlog is historical - but
# nothing was checking, and `sent` is precisely the field a reader trusts.
#
# Window-scoped like J1: the backlog is reported every run, and only a row claimed sent inside the
# window fails the gate, because a gate that is red for last quarter's rows stops being a gate.
# Match by TIME as well as by body: a template or a re-prefixed send must not hide a real send.
# ---------------------------------------------------------------------------------------
try:
    _db = _resolve_app_db()
    _q = ro(_db)
    try:
        _win = int(os.environ.get("QUEUE_SENT_WINDOW_DAYS", "7") or 7)
        _cut = (datetime.now(timezone.utc) - timedelta(days=_win)).isoformat()
        # ro() does not set a row_factory: name the columns rather than assuming a mapping.
        _claimed = [{"id": r[0], "body": r[1], "sent_at": r[2]} for r in _q.execute(
            "select id, body, sent_at from owner_message_queue "
            "where status='sent' and sent_at is not null and sent_at >= ?", (_cut,))]
        _backlog = _q.execute(
            "select count(*) from owner_message_queue where status='sent' "
            "and sent_at is not null and sent_at < ?", (_cut,)).fetchone()[0]
        _missing = []
        for _row in _claimed:
            _hit = _q.execute(
                "select 1 from sms_log where to_number=? "
                "and (abs(julianday(created_at)-julianday(?)) < 0.02 "
                "     or substr(coalesce(body,''),1,60)=substr(coalesce(?,''),1,60)) "
                "limit 1",
                (OWNER_NUMBER, _row["sent_at"], _row["body"] or "")).fetchone()
            if not _hit:
                _missing.append(_row["id"])
        check("K1 a queue row marked 'sent' has a sms_log row behind it",
              not _missing,
              "%d row(s) claimed sent in the last %d days; %d of them have NO sms_log row within "
              "~30 minutes, so 'sent' there means nothing we can show. %d older row(s) carry the "
              "same claim and are reported, not failed: #%s"
              % (len(_claimed), _win, len(_missing), _backlog,
                 ",".join(str(i) for i in _missing[:8]) or "none"))
    finally:
        _q.close()
except Exception as exc:                                       # noqa: BLE001
    check("K1 a queue row marked 'sent' has a sms_log row behind it", False,
          "%s: %s" % (type(exc).__name__, exc))


# ---------------------------------------------------------------------------------------
# K2: the app's send choke point must still reach the relay.
#
# The three content guards - quiet hours, credential_request, internal_prose - live in
# `owner_text_relay.submit()`. They apply to every app send only because
# `sms_service.send_message` calls `submit(door="app", ...)`. Nothing declares that dependency and
# nothing tested it: a refactor removing one call would strip all three guards from every app
# message, and every individual guard test would still pass.
#
# A SOURCE-LEVEL CHECK ON PURPOSE. The alternative is sending a probe text, and on this channel
# sending is the expensive thing. This reads the file for the call and the door name; behaviour is
# covered by the relay's own checks and the replay.
# ---------------------------------------------------------------------------------------
try:
    _svc = BIN.parent / "opt" / "company" / "app" / "sms_service.py"
    _svc = Path(os.environ.get("SMS_SERVICE_PY", "/opt/company/app/sms_service.py"))
    if not _svc.exists():
        check("K2 the app send path still calls owner_text_relay.submit", True,
              "NOT MEASURED: %s not present on this host" % _svc)
    else:
        _src = _svc.read_text(encoding="utf-8", errors="replace")
        _calls = _src.count("owner_text_relay.submit(")
        _door = 'door="app"' in _src
        _loads = "owner_text_relay" in _src
        check("K2 the app send path still calls owner_text_relay.submit",
              bool(_calls) and _door,
              "%s: %d submit() call(s), door=\"app\" present=%s, relay referenced=%s -- if this "
              "fails, the quiet-hours, credential and internal-prose guards are NOT on app sends"
              % (_svc.name, _calls, _door, _loads))
except Exception as exc:                                       # noqa: BLE001
    check("K2 the app send path still calls owner_text_relay.submit", False,
          "%s: %s" % (type(exc).__name__, exc))


# ---------------------------------------------------------------------------------------
# K3: a gate_error is an outage, not a policy refusal.
#
# Measured 2026-10-19 from owner_text_decision: 2,780 rows with code `gate_error`, EVERY ONE in the
# first five days of October, all saying the same thing - the owner-text ledger was unreadable
# because of a getattr called with seven arguments. One internal bug made the gate raise on every
# owner send for five days; the broad `except` refused rather than sending blind, which is right per
# message and, in aggregate, is a channel outage. Nothing escalated.
#
# `ok` (3827) and the policy codes - awaiting_reply, too_long, rate_floor, similar_hold - are the
# gate working. `gate_error` is the gate BROKEN. It gets its own invariant so the next occurrence is
# a red check within a day rather than a number found five months later.
# ---------------------------------------------------------------------------------------
try:
    _q = ro(_resolve_app_db())
    try:
        _win = int(os.environ.get("GATE_ERROR_WINDOW_DAYS", "1") or 1)
        _cut = (datetime.now(timezone.utc) - timedelta(days=_win)).isoformat()
        _recent = _q.execute(
            "select count(*) from owner_text_decision "
            "where code='gate_error' and created_at >= ?", (_cut,)).fetchone()[0]
        _total = _q.execute(
            "select count(*) from owner_text_decision where code='gate_error'").fetchone()[0]
        _why = _q.execute(
            "select why from owner_text_decision where code='gate_error' "
            "order by created_at desc limit 1").fetchone()
        check("K3 the owner-text gate is not refusing because it is broken",
              _recent == 0,
              "%d gate_error decision(s) in the last %d day(s); %d all-time. %s"
              % (_recent, _win, _total,
                 ("Most recent: %s" % str(_why[0])[:150]) if _why else "none on record"))
    finally:
        _q.close()
except Exception as exc:                                       # noqa: BLE001
    check("K3 the owner-text gate is not refusing because it is broken", False,
          "%s: %s" % (type(exc).__name__, exc))


# ---------------------------------------------------------------------------------------
# K4: a retry storm is an outage of one producer.
#
# Measured 2026-10-19: 1,273 `too_long` refusals, dominated by a few bodies retried hundreds of
# times - one 321-character reminder 842 times, an 811-character one 291 times. Each refusal is a
# sane decision about one message; 842 of them about the same message is a LOOP, and from outside the
# table a loop and a policy look identical: refusals, each with a reason.
#
# So: no single body may be refused more than RETRY_STORM_LIMIT times inside the window.
# ---------------------------------------------------------------------------------------
try:
    _q = ro(_resolve_app_db())
    try:
        _win = int(os.environ.get("RETRY_STORM_WINDOW_HOURS", "24") or 24)
        _limit = int(os.environ.get("RETRY_STORM_LIMIT", "5") or 5)
        _cut = (datetime.now(timezone.utc) - timedelta(hours=_win)).isoformat()
        _rows = _q.execute(
            "select substr(coalesce(body_head,''),1,40) h, count(*) n from owner_text_decision "
            "where allowed=0 and created_at >= ? group by 1 having count(*) > ? "
            "order by n desc limit 5", (_cut, _limit)).fetchall()
        _worst = _q.execute(
            "select substr(coalesce(body_head,''),1,40) h, count(*) n from owner_text_decision "
            "where allowed=0 and created_at >= ? group by 1 order by n desc limit 1",
            (_cut,)).fetchone()
        check("K4 no producer is retrying one body into a refusal loop",
              not _rows,
              "%d body/bodies refused more than %d times in %d h%s"
              % (len(_rows), _limit, _win,
                 ("" if not _rows else ": " + "; ".join(
                     "%.40s x%d" % (r[0], r[1]) for r in _rows))
                 + (" | worst overall: %.40s x%d" % (_worst[0], _worst[1]) if _worst else "")))
    finally:
        _q.close()
except Exception as exc:                                       # noqa: BLE001
    check("K4 no producer is retrying one body into a refusal loop", False,
          "%s: %s" % (type(exc).__name__, exc))

print("TEXT-HEALTH %s" % datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
failed = 0
for name, ok, evidence in results:
    if not ok:
        failed += 1
    print("%s  %s" % ("OK  " if ok else "FAIL", name))
    print("       %s" % evidence)
print("RESULT: %d check(s), %d FAIL" % (len(results), failed))
sys.exit(1 if failed else 0)
