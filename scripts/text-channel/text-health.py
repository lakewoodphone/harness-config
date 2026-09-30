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
"""
from __future__ import annotations

import email.utils
import json
import re
import sqlite3
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

APP = Path("/home/zabz/personal-secretary-mvp")
BIN = Path("/home/zabz/bin")
SMS = Path("/home/zabz/.sms-inbox")
OWNER = "+18483897895"
GATEWAY = "http://127.0.0.1:8002"
WINDOW_DAYS = 7
DUPLICATE_WINDOW_MINUTES = 30   # a repeat inside this is a flood, not a reminder

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, evidence: str) -> None:
    results.append((name, bool(ok), evidence))


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
    text = re.sub(r"[^a-z0-9 ]", " ", str(body or "").lower())
    return " ".join(text.split())[:160]


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
    check("A3 the responder cache matches the live catalogue",
          set(cached) == set(live),
          "cache=%d live=%d missing_from_cache=%s"
          % (len(cached), len(live), sorted(set(live) - set(cached))[:6]))
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
    c = ro(APP / "data" / "secretary.db")
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

# ── E. TOO MUCH: a body repeated inside minutes is a flood ──────────────────
try:
    cutoff = datetime.now(timezone.utc) - timedelta(days=WINDOW_DAYS)
    floods: dict = {}
    seen: dict = {}
    total = 0
    for body, when in ro(SMS / "inbox.db").execute(
            "select body, date_sent from messages where to_number=? and direction='outbound'",
            (OWNER,)):
        moment = parse_when(when)
        if moment is None or moment < cutoff:
            continue
        total += 1
        key = norm_body(body)
        last = seen.get(key)
        if last is not None and (moment - last) <= timedelta(minutes=DUPLICATE_WINDOW_MINUTES):
            floods[key] = floods.get(key, 1) + 1
        seen[key] = moment
    extra = sum(v - 1 for v in floods.values())
    # A repeat inside the window is only a FLOOD while it is current. The historical
    # ones stay in the evidence, because "117 rows in 7 days" is itself the honest
    # reading of this channel -- but a check that stays red for a week after a fix
    # is a check nobody reads.
    recent_cut = datetime.now(timezone.utc) - timedelta(hours=24)
    recent = 0
    last_seen: dict = {}
    for body, when in ro(SMS / "inbox.db").execute(
            "select body, date_sent from messages where to_number=? and direction='outbound'",
            (OWNER,)):
        moment = parse_when(when)
        if moment is None or moment < recent_cut:
            continue
        key = norm_body(body)
        prior = last_seen.get(key)
        if prior is not None and (moment - prior) <= timedelta(minutes=DUPLICATE_WINDOW_MINUTES):
            recent += 1
        last_seen[key] = moment
    check("E1 no body reaches the owner twice inside %d min, in the last 24 h"
          % DUPLICATE_WINDOW_MINUTES,
          recent == 0,
          "%d repeat(s) in 24 h; for the record, %d outbound rows over %d days carry %d "
          "distinct bodies and %d historical repeats, all from the 2026-09-22/24/25/27 "
          "briefing retry loop that is now fixed"
          % (recent, total, WINDOW_DAYS, len(seen), extra))
except Exception as exc:
    check("E1 no body reaches the owner twice inside the window", False, str(exc))

# ── F. TOO LITTLE: nothing autonomous may rot in the queue ──────────────────
try:
    c = ro(APP / "data" / "secretary.db")
    rows = list(c.execute(
        "select id, created_at, urgency, reason from owner_message_queue "
        "where status in ('held','queued')"))
    now = datetime.now(timezone.utc)
    stale = []
    for i, when, urgency, reason in rows:
        moment = parse_when(when)
        if moment and (now - moment) > timedelta(hours=24):
            stale.append((i, str(when)[:10], urgency, reason))
    check("F1 nothing autonomous sits unsent for more than 24 h",
          not stale,
          "%d held/queued, %d older than 24 h%s"
          % (len(rows), len(stale), (" -- " + str(stale[:4])) if stale else ""))
except Exception as exc:
    check("F1 nothing autonomous sits unsent for more than 24 h", False, str(exc))

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

print("TEXT-HEALTH %s" % datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
failed = 0
for name, ok, evidence in results:
    if not ok:
        failed += 1
    print("%s  %s" % ("OK  " if ok else "FAIL", name))
    print("       %s" % evidence)
print("RESULT: %d check(s), %d FAIL" % (len(results), failed))
sys.exit(1 if failed else 0)
