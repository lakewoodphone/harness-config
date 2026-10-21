#!/usr/bin/env python3
"""owner-queue-ingest-gv — turn Google Voice forwards in Gmail into owner-queue items.

WHY THIS EXISTS AND WHY IT IS HERE

The owner's rule (2026-10-18, verbatim): "dialpad calls sms and voicemail do not count. I only want
personal ones ... Google voice numbers and you do have access to my Google voice numbers because they
get forwarded to my email." So the personal channel is Google Voice and the ONLY working access path
is the forwarding mail. Three measured facts make this the place it has to live:

  * `google_voice_secretary_log` `gmail_forward` rows stop 2026-07-03 while the mailbox keeps
    receiving -- a dead reader over a live channel. Nothing derived from that table can be trusted.
  * `email_triage_log` holds GV senders only to 2026-07-05 and is ~21 rows/day across five accounts,
    far below real volume, so a queue fed from it would look complete and be wrong.
  * Reading the mailbox directly works: 624 forwards in 45 days (538 sms, 66 missed calls,
    20 voicemails), 0 unparsed by `gv_email_handler.parse_gv_email`.

It runs under the app's venv (`/root/personal-secretary-mvp/.venv/bin/python`) because it imports the
real Gmail client and the real GV parser -- never a second copy of either. It writes ONLY
`owner_decision_queue`, the one queue table.

  owner-queue-ingest-gv.py --days 2               # normal run
  owner-queue-ingest-gv.py --days 45 --explain    # every item's verdict and reason, no writes
  owner-queue-ingest-gv.py --days 45 --explain --only-dropped
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timezone

APP_ROOT = os.environ.get("PS_APP_ROOT", "/root/personal-secretary-mvp")
DEFAULT_DB = os.environ.get("OWNER_QUEUE_DB", "/root/authority.db")
sys.path.insert(0, APP_ROOT)

# THE CWD IS LOAD-BEARING, and it is not obvious. `gmail_service._tokens_dir` defaults to the
# RELATIVE path `data/gmail_tokens`, so it resolves against the process cwd. Run from /root and
# every account reports "not authenticated" while the tokens sit in the app checkout; measured
# 2026-10-18, and it looked exactly like a credential outage. Pin it here so this script is
# correct from any caller, including `owner-queue.py ingest` and a cron.
if os.path.isdir(APP_ROOT):
    os.chdir(APP_ROOT)

GV_QUERY = "from:voice-noreply@google.com OR from:txt.voice.google.com"
# Which mailbox receives which GV number. Mirrors GV_ACCOUNT_MAP in gv_email_handler, imported
# below at runtime; declared here only so --accounts can be overridden for a probe.
GV_ACCOUNTS = ("eliyahuzabrowsky@gmail.com", "ezabz68@gmail.com")


# ── classification (v2, written from the corpus and then corrected against it) ──
#
# The 45-day corpus is 624 forwards: 538 sms, 66 missed calls, 20 voicemails. What it is actually made
# of, in volume order: one family group relay (179 from a single number), shortcode senders (Walmart,
# Home Depot, Amex, Chase, PayPal, Telnyx, DHL), daily zmanim/candle-lighting alerts (43),
# mazel-tov/simcha broadcast lists (41), one data-recovery vendor that sends a robot message per event
# (15+), and spend notifications from a wallet app. One-to-one personal traffic is a small minority.
#
# v1 of these rules queued 256 of 624. That is not a queue, so v2 adds what the failures taught:
# sustained-volume senders collapse to one item per day; missed calls and voicemails collapse per
# sender per day; vendor robots and our own alert texts never enter; and a voicemail is not
# "critical" merely for saying "call me back" -- robocalls say that too.

BULK_SENDERS = (
    "igud talmidei fallsburg", "foyer public", "onepay", "paypal", "mobilesentrix",
    "telnyx", "walmart", "home depot", "chase", "amex", "dhl", "ups", "fedex",
    "bilt", "irs", "usps", "amazon", "aliexpress", "stripe", "robinhood", "coinbase",
    "verizon", "at&t", "t-mobile", "us mobile", "optimum", "pseg", "nj natural",
    "wellpoint", "pinstriped suits",
)

#: A sender that produced this many messages across the window is a group relay, not a person
#: sending him separate things. Measured: the family relay produced 179.
RELAY_MIN_MESSAGES = 8

RE_OTP = re.compile(
    r"\b(one[-\s]?time\s+(?:code|passcode|password)|verification\s+code|"
    r"your\s+\w+\s+code\s+is|use\s+code|passcode|otp|do\s+not\s+share|"
    r"confirm\s+you.?re\s+adding|is\s+your\s+one[-\s]?time|account\s+code|"
    # Word order varies and the number comes first: "530226 is your GitHub
    # authentication code" reached the queue as a personal message before this.
    r"\b\d{4,8}\s+is\s+your\b|\byour\s+\w+\s+(?:authentication|login)\s+code\b)\b", re.I)

#: Toll-free marketing. A one-off promo from an 8xx number is never his business.
RE_TOLLFREE = re.compile(r"^\+?1?(800|833|844|855|866|877|888)\d{7}$")
RE_PROMO = re.compile(
    r"\b(introducing|new\s+menu|order\s+now|limited\s+time|% off|deal|promo|"
    r"try\s+(?:our|it)|free\s+delivery|coupon|sale\s+ends)\b", re.I)

RE_SHIPPING = re.compile(
    r"\b(order\s*#|has\s+been\s+shipped|has\s+been\s+delivered|out\s+for\s+delivery|"
    r"tracking\s+(?:information|number)|proof\s+of\s+delivery|delivery\s+TODAY|"
    r"arriving\s+today|now\s+registered\s+in\s+our)\b", re.I)

RE_ZMANIM = re.compile(
    r"\b(krias\s*shema|candle\s+lighting|zmanim|davening\s+times|"
    r"have\s+a\s+nice\s+day!?\s*Sponsored|shabbos\s+begins)\b", re.I)

RE_SIMCHA = re.compile(
    r"\b(mazel\s*tov|mazal\s*tov|shalom\s*zachor|shulem\s*zucher|kidush|kiddush|"
    r"chasuna|chasune|bris\b|bar\s*mitzva|bar\s*mitzvah|pidyon\s+haben|petirah|nifter|"
    r"levaya|nichum\s*aveilim|shiva\s+schedule|baruch\s*dayan)\b", re.I)

# OWNER, 2026-10-21, verbatim: "that channel is a large channel for for everyone from my college
# and I don't need to know most stuff that happened there." Simcha broadcasts from a college-wide
# community channel are noise to him; a levaya / aveilim notice from the same sender is KEPT,
# because the 2026-10-18 note below records that those are the ones a person here acts on.
SUPPRESSED_SIMCHA_SENDERS = ("+13217755221",)
RE_AVEILIM = re.compile(
    r"\b(levaya|nichum\s*aveilim|shiva\s+schedule|baruch\s*dayan|petirah|nifter|aveilim)\b", re.I)


def _community_noise(item: dict, body: str) -> bool:
    """True when this broadcast comes from a sender the owner asked to stop hearing from,
    and it is not a levaya/aveilim notice."""
    digits = re.sub(r"\D", "", str(item.get("phone") or ""))
    if not digits:
        return False
    wanted = {re.sub(r"\D", "", s)[-10:] for s in SUPPRESSED_SIMCHA_SENDERS}
    if digits[-10:] not in wanted:
        return False
    return not RE_AVEILIM.search(body)

NO_BODY = frozenset({"", "mms received", "test sms", "tdpt", "mms", "sms received"})
RE_SHORTCODE = re.compile(r"^\d{4,6}$")
RE_DATA_USAGE = re.compile(r"current\s+period\s+is\s+[\d.]+\s+megabytes", re.I)

#: A vendor's robot telling him it sent an email. Never his business: the email itself is.
RE_VENDOR_ROBOT = re.compile(
    r"(we\s+just\s+emailed\s+you|requires\s+your\s+(?:response|approval)|"
    r"money\s+request|payment\s+request|please\s+(?:review|respond)\s+at|"
    r"just\s+spent\s+\$|you\s+just\s+spent|your\s+bill\s+is\s+ready|"
    r"points\s+(?:just\s+)?landed|has\s+been\s+added\s+to\s+your|"
    r"informational\s+call|you\s+have\s+received\s+an?\s+important\s+message)", re.I)

#: Our own systems text him through Google Voice. A queue that shows him our alerts is a loop.
RE_SELF_ALERT = re.compile(
    r"(google\s+voice\s+monitoring\s+is\s+blind|lakewood\s+phone\s*&\s*tech:|"
    r"reminder:\s*pay\b|automatic\s+notice\s+check|is\s+your\s+secretary|"
    r"owner[-\s]?queue|decision\s+queue)", re.I)

#: Robocall / spam voicemail. Their transcripts are garbled and always ask for a callback.
RE_ROBOCALL = re.compile(
    r"(informational\s+call|important\s+message\s+for|you\s+have\s+received|"
    r"established\s+in|play\s+message|accountchooser|"
    r"this\s+is\s+an\s+important\s+message|press\s+\d|"
    r"your\s+(?:warranty|vehicle|health)\s+plan|final\s+notice|"
    r"we\s+(?:are|were)\s+calling\s+(?:about|from)\s+your)", re.I)

RE_ASK = re.compile(
    r"(\?|\b(can|could|would|will)\s+you\b|\bare\s+you\b|\bdo\s+you\b|\bdid\s+you\b|"
    r"\bplease\b|\blet\s+me\s+know\b|\bwhat\s+do\s+you\s+think\b|\bshould\s+(?:i|we)\b|"
    r"\bneed\s+(?:you|your)\b|\bwaiting\s+(?:on|for)\s+you\b|\bcall\s+me\b|\bget\s+back\s+to\s+me\b|"
    r"\bany\s+(?:way|idea|update|ideas)\b|\bupdate\s+on\b|\bapprove|\bconfirm|\bdecide|\bchoose|"
    r"\bwhich\s+one\b|\bwhat(?:'s|\s+is)\s+your\b)", re.I)

RE_DECISION = re.compile(
    r"\b(decide|approve|authori[sz]e|sign\s+off|which\s+one|should\s+i|should\s+we|"
    r"do\s+you\s+want|is\s+it\s+ok|ok\s+to|go\s+ahead|buy|purchase|pay|refund|"
    r"cancel|return|court|lawyer|attorney|contract|sign)\b", re.I)

RE_MONEY = re.compile(r"\$\s?([\d,]+(?:\.\d{2})?)")
RE_DEADLINE = re.compile(
    r"\b(today|tonight|tomorrow|asap|urgent|immediately|by\s+\w+day|"
    r"this\s+week|before\s+\d|due\b|deadline)\b", re.I)
RE_CALLBACK = re.compile(
    r"\b(call\s+(?:me\s+)?back|give\s+me\s+a\s+call|call\s+me|ring\s+me|"
    r"get\s+back\s+to\s+me|reach\s+me)\b", re.I)


def _norm(s: str) -> str:
    return " ".join((s or "").split()).strip()


#: What carrier caller-ID puts in the name field when it has nothing. These are not names,
#: and treating them as one promoted "Missed call from Unknown Caller" above real callers.
NON_NAMES = frozenset({
    "unknown caller", "unknown", "private", "private caller", "wireless caller",
    "toll free call", "toll-free call", "restricted", "no caller id", "anonymous",
})


def _is_real_name(name: str) -> bool:
    # Caller-ID labels arrive with trailing punctuation ("Unknown Caller."), which defeated an
    # exact membership test and let it rank above real callers.
    n = (name or "").strip().strip(" .,:;-").lower()
    if not n or n in NON_NAMES:
        return False
    return not re.sub(r"[\s\-()+.]", "", n).isdigit()


#: Google Voice appends the same boilerplate to every forward. It is not part of what anyone
#: said, it defeats exact body comparisons ("MMS Received" never equals "MMS Received To
#: respond ..."), and it is what turns a one-word text into a 200-character queue title.
_BODY_CUTS = (
    "To respond to this text message",
    "YOUR ACCOUNT HELP CENTER",
    "This email was sent to you because",
    "To respond to this message, launch Google Voice",
    "play message",
)


def clean_body(text: str) -> str:
    """The words a person actually sent, with the forwarder's boilerplate removed."""
    t = text or ""
    low = t.lower()
    for cut in _BODY_CUTS:
        i = low.find(cut.lower())
        if i >= 0:
            t = t[:i]
            low = low[:i]
    return _norm(t)


def _money_value(text: str) -> float | None:
    best = None
    for m in RE_MONEY.finditer(text or ""):
        try:
            v = float(m.group(1).replace(",", ""))
        except ValueError:
            continue
        if best is None or v > best:
            best = v
    return best


def classify(item: dict, *, sender_total: int = 0) -> dict:
    """One verdict per parsed GV item: DROP, DIGEST, ATTENTION or DECISION."""
    body = clean_body(item.get("body"))
    name = _norm(item.get("name"))
    low_name = name.lower()
    low_body = body.lower()
    kind = item.get("type")

    out = {"verdict": "ATTENTION", "reason": "", "ask": False,
           "money": None, "deadline": False, "tier": "medium"}

    if kind == "voicemail":
        if RE_ROBOCALL.search(body) or RE_VENDOR_ROBOT.search(body):
            return out | {"verdict": "DROP", "reason": "robocall or vendor robot voicemail"}
        if not body:
            return out | {"verdict": "DROP", "reason": "voicemail with no transcript"}
        named = _is_real_name(name)
        if RE_CALLBACK.search(body) and named:
            return out | {"verdict": "ATTENTION", "tier": "critical",
                          "ask": True,
                          "reason": "voicemail from %s asking to be called back" % name}
        return out | {"verdict": "ATTENTION", "tier": "high", "ask": bool(RE_CALLBACK.search(body)),
                      "reason": "voicemail left for him"}

    if kind == "missed_call":
        # MEASURED 2026-10-18 over 7 days: 7 missed calls from numbers not in his contacts, all
        # dropped. That is the right call for one of them and the wrong call for the seven: he runs a
        # shop, every one of those could be a customer, and "nothing to act on" is my judgement, not
        # his. They are not queued one by one -- they fold into ONE row a week that names the
        # numbers, so he can see at a glance that seven strangers rang and ring back the ones he
        # recognises. Nothing is dropped and nothing floods.
        if not _is_real_name(name):
            return out | {"verdict": "DIGEST", "tier": "low",
                          "reason": "missed call from an unrecognised number"}
        return out | {"verdict": "ATTENTION", "tier": "medium",
                      "reason": "missed call from %s" % name}

    if low_body in NO_BODY or (len(body) <= 3 and not name):
        # The set is of BODIES. Checking the sender name against it let "MMS Received"
        # through as a queue item, which is a queue telling him nothing happened.
        return out | {"verdict": "DROP", "reason": "empty or receipt-only body"}
    if RE_SHORTCODE.search(name):
        return out | {"verdict": "DROP", "reason": "shortcode sender (%s)" % name}
    if RE_SELF_ALERT.search(body):
        return out | {"verdict": "DROP", "reason": "our own alert text, not a person"}
    if RE_DATA_USAGE.search(body):
        return out | {"verdict": "DROP", "reason": "carrier data-usage notice"}
    if RE_VENDOR_ROBOT.search(body):
        return out | {"verdict": "DROP", "reason": "vendor robot message"}
    if any(b in low_name for b in BULK_SENDERS):
        return out | {"verdict": "DROP", "reason": "bulk sender: %s" % name}
    # A community announcement is not marketing, and it must be checked BEFORE the bulk-sender rule
    # below, which is what ate it. MEASURED 2026-10-18 over 7 days: "Igud Talmidei Fallsburg: Nichum
    # Aveilim Hours" and a Baruch Dayan HaEmes levaya notice were dropped as `bulk sender in body`.
    # Those are the notices a person actually acts on in this community -- and the rule that dropped
    # them was written to stop retail marketing under a bare-number caller-ID.
    if RE_SIMCHA.search(body) and not RE_ASK.search(body):
        if _community_noise(item, body):
            return out | {"verdict": "DROP",
                          "reason": "college-community broadcast, owner asked for none (2026-10-21)"}
        return out | {"verdict": "DIGEST",
                      "reason": "simcha/levaya/community announcement (broadcast, folded)"}
    # A bulk sender whose caller-ID is a bare number names itself in the BODY prefix
    # ("Wellpoint: ...", "Pinstriped Suits: ..."). Measured: without this, insurance and
    # retail marketing reached the queue under a phone-number name.
    head = low_body[:48]
    for b in BULK_SENDERS:
        if head.startswith(b + ":") or head.startswith(b + " :"):
            return out | {"verdict": "DROP", "reason": "bulk sender in body: %s" % b}
    if RE_OTP.search(body):
        return out | {"verdict": "DROP", "reason": "one-time code / account security"}
    if RE_TOLLFREE.match(re.sub(r"[\s\-()]", "", item.get("phone") or "")) and RE_PROMO.search(body):
        return out | {"verdict": "DROP", "reason": "toll-free marketing message"}
    if RE_SHIPPING.search(body):
        return out | {"verdict": "DROP", "reason": "order or parcel lifecycle"}
    if RE_ZMANIM.search(body):
        return out | {"verdict": "DROP", "reason": "scheduled zmanim/candle-lighting alert"}

    if sender_total >= RELAY_MIN_MESSAGES:
        return out | {"verdict": "DIGEST", "tier": "low",
                      "ask": bool(RE_ASK.search(body)),
                      "reason": "group relay (%d messages in the window)" % sender_total}
    if RE_SIMCHA.search(body) and not RE_ASK.search(body):
        if _community_noise(item, body):
            return out | {"verdict": "DROP",
                          "reason": "college-community broadcast, owner asked for none (2026-10-21)"}
        return out | {"verdict": "DIGEST", "reason": "simcha/levaya listing (broadcast, folded)"}

    money = _money_value(body)
    out["money"] = money
    out["ask"] = bool(RE_ASK.search(body))
    out["deadline"] = bool(RE_DEADLINE.search(body))

    if RE_DECISION.search(body) and (money is not None or out["ask"]):
        return out | {"verdict": "DECISION", "tier": "high",
                      "reason": "asks him to choose/approve/commit" +
                                (" ($%.2f)" % money if money else "")}
    if out["ask"]:
        return out | {"tier": "high" if out["deadline"] else "medium",
                      "reason": "a person asking him something"}
    if money is not None:
        return out | {"tier": "medium", "reason": "mentions money ($%.2f)" % money}
    if out["deadline"]:
        return out | {"tier": "medium", "reason": "mentions a date or deadline"}
    return out | {"tier": "low", "reason": "personal message, no ask and no date"}


def resolve_names(items: list[dict]) -> int:
    """Give a name to numbers we already know. Returns how many were resolved.

    "Missed call from (848) 224" is not actionable; the corpus has 66 missed calls and many are
    bare numbers. The comms index already holds the person layer (people/person_alias), so this
    reads it instead of guessing. Read-only, and silent if the index is absent.
    """
    import glob
    path = os.environ.get("COMMS_DB") or os.path.expanduser("~/.fsearch/comms.db")
    if not os.path.exists(path):
        cands = glob.glob(os.path.expanduser("~/.fsearch/comms*.db"))
        path = cands[0] if cands else ""
    if not path or not os.path.exists(path):
        return 0
    digits = []
    for it in items:
        d = re.sub(r"\D", "", it.get("phone") or "")
        if len(d) == 11 and d.startswith("1"):
            d = d[1:]
        it["_digits"] = d if len(d) == 10 else ""
        if it["_digits"]:
            digits.append(it["_digits"])
    if not digits:
        return 0
    try:
        con = sqlite3.connect("file:%s?mode=ro" % path, uri=True, timeout=30)
    except sqlite3.Error:
        return 0
    resolved = 0
    try:
        for it in items:
            if it.get("name") or not it.get("_digits"):
                continue
            try:
                row = con.execute(
                    "SELECT COALESCE(p.display_name,'') FROM person_alias a"
                    "  JOIN people p ON p.person_key = a.person_key"
                    " WHERE a.alias_value = ? AND a.alias_kind='phone'"
                    "   AND COALESCE(p.display_name,'') <> '' LIMIT 1",
                    (it["_digits"],)).fetchone()
            except sqlite3.Error:
                return resolved
            if row and row[0]:
                it["name"] = _norm(row[0])
                it["name_source"] = "comms-index"
                resolved += 1
    finally:
        con.close()
    return resolved


# ── Gmail access ──────────────────────────────────────────────────────────
def load_settings():
    """The app's settings object. `get_settings` does NOT exist in app.config --
    only `settings` -- so both shapes are tried, same as owner_attention_sweep."""
    try:
        from app.config import get_settings as fn  # type: ignore

        if callable(fn):
            return fn()
        return fn
    except Exception:
        pass
    from app.config import settings as s  # type: ignore

    return s


def fetch(accounts, days: int, verbose: bool) -> tuple[list[dict], list[str]]:
    from app.services import gmail_service
    from app.services.gv_email_handler import parse_gv_email

    settings = load_settings()
    items: list[dict] = []
    errors: list[str] = []
    for account in accounts:
        try:
            msgs = gmail_service.search_messages(
                settings, account=account, query=GV_QUERY + " newer_than:%dd" % days,
                max_results=3000)
        except Exception as exc:  # noqa: BLE001
            errors.append("%s search: %s: %s" % (account, type(exc).__name__, exc))
            continue
        if verbose:
            print("  %s: %d message(s)" % (account, len(msgs)), file=sys.stderr)
        for m in msgs:
            try:
                full = gmail_service.read_message(
                    settings, account=account, message_id=m.get("id"))
            except Exception as exc:  # noqa: BLE001
                errors.append("%s read %s: %s" % (account, m.get("id"), exc))
                continue
            headers = full.get("headers") or {}
            sender = headers.get("From") or full.get("from") or m.get("from") or ""
            subject = headers.get("Subject") or full.get("subject") or m.get("subject") or ""
            body = full.get("body") or full.get("body_text") or ""
            parsed = parse_gv_email(subject=subject, body_text=body,
                                    from_address=sender, account_email=account)
            if parsed is None:
                errors.append("%s: unparsed GV mail %s (%s)" % (account, m.get("id"), subject[:40]))
                continue
            ts = full.get("internal_ts") or m.get("internal_ts") or 0
            try:
                when = datetime.fromtimestamp(float(ts) / 1000.0, tz=timezone.utc)
            except (TypeError, ValueError, OSError):
                when = datetime.now(timezone.utc)
            items.append({
                "account": account,
                "message_id": m.get("id"),
                "thread_id": full.get("thread_id") or m.get("thread_id") or "",
                "when": when,
                "day": when.strftime("%Y-%m-%d"),
                "iso": when.isoformat(),
                "type": parsed["type"],
                "name": _norm(parsed["contact_name"]),
                "phone": _norm(parsed["contact_phone"]),
                "body": clean_body(parsed["body"]),
                "gv_number": parsed.get("gv_number") or "",
            })
    return items, errors


# ── grouping into queue items ─────────────────────────────────────────────
def build_queue_items(items: list[dict]) -> tuple[list[dict], list[dict]]:
    """Classify, collapse, dedupe. Returns (queue_items, dropped).

    Collapsing happens here rather than at render time so the queue table holds one row per thing
    he must actually deal with -- which is what makes a dismissal stick to the thing, not a message.
    """
    sender_total: dict[str, int] = defaultdict(int)
    for it in items:
        sender_total[it.get("phone") or it.get("name")] += 1

    dropped: list[dict] = []
    kept: list[dict] = []
    digests: dict[tuple, list[dict]] = defaultdict(list)
    by_key: dict[tuple, dict] = {}

    for it in items:
        v = classify(it, sender_total=sender_total.get(it.get("phone") or it.get("name"), 0))
        rec = dict(it, **v)
        if v["verdict"] == "DROP":
            dropped.append(rec)
            continue
        if v["verdict"] == "DIGEST":
            # A relay collides on (sender, ISO week), not on (sender, day): one row per day
            # produced 15 near-identical family-chat rows across a 45-day window, which is the
            # same failure as not collapsing at all. The week key also means a dismissed relay
            # row stays dismissed, and next week's chat legitimately reappears.
            week = it["when"].isocalendar()
            weekkey = "%d-W%02d" % (week[0], week[1])
            if "unrecognised number" in (v.get("reason") or ""):
                # ONE row for every stranger who rang this week, not one row per stranger: seven
                # separate rows is the flood the old DROP rule existed to prevent.
                digests[("__unknown_calls__", weekkey)].append(rec)
            elif "group relay" in (v.get("reason") or "") or "community announcement" in (
                    v.get("reason") or ""):
                digests[(it.get("phone") or it.get("name"), weekkey)].append(rec)
            else:
                digests[(it.get("phone") or it.get("name"), it["day"])].append(rec)
            continue
        if rec["type"] in ("missed_call", "voicemail"):
            # One row per sender per day: four calls from the same number in one day is one thing
            # that happened, not four.
            k = (rec["type"], rec.get("phone") or rec.get("name"), rec["day"])
            prior = by_key.get(k)
            if prior:
                prior["_count"] = (prior.get("_count") or 1) + 1
                if len(rec["body"]) > len(prior.get("body") or ""):
                    prior["body"] = rec["body"]
                    prior["when"] = rec["when"]
                    prior["iso"] = rec["iso"]
                prior["ask"] = prior.get("ask") or rec.get("ask")
                continue
            rec["_count"] = 1
            by_key[k] = rec
            kept.append(rec)
            continue
        # An identical text arriving twice (webhook + forward) is one text.
        k = (rec.get("phone") or rec.get("name"), rec["day"], (rec.get("body") or "")[:80])
        prior = by_key.get(k)
        if prior:
            prior["_count"] = (prior.get("_count") or 1) + 1
            continue
        rec["_count"] = 1
        by_key[k] = rec
        kept.append(rec)

    for (who, bucket), group in digests.items():
        group.sort(key=lambda r: r["when"])
        speakers = []
        for r in group:
            if r["name"] and r["name"] not in speakers:
                speakers.append(r["name"])
        asks = [r["body"] for r in group if r.get("ask") and r["body"]]
        if who == "__unknown_calls__":
            # Name the numbers. "5 missed calls" is a statistic; the numbers are the thing he can act
            # on, and he is the only one who knows which of them he recognises.
            nums = []
            for r in group:
                n = r.get("phone") or r.get("name")
                if n and n not in nums:
                    nums.append(n)
            bodies = [_pretty_number(x) for x in nums[:10]]
            name, phone = "unrecognised callers", ""
            reason = "%d missed call(s) this week from numbers not in your contacts" % len(group)
        else:
            bodies = asks[:2] or [r["body"] for r in group if r["body"]][:2]
            name = group[0]["name"] or group[0]["phone"]
            phone = group[0]["phone"]
            if "community announcement" in (group[0].get("reason") or ""):
                reason = "%d community announcement(s) this week, folded into one" % len(group)
            else:
                span = ("this week" if "-W" in str(bucket) else "this day")
                reason = "%d message%s %s, folded into one" % (
                    len(group), "" if len(group) == 1 else "s", span)
        n = len(group)
        kept.append({
            "account": group[0]["account"],
            "thread_id": group[0]["thread_id"],
            "message_id": group[0].get("message_id"),
            "when": group[-1]["when"],
            "day": group[-1]["day"],
            "bucket": bucket,
            "iso": group[-1]["iso"],
            "type": "digest",
            "name": name,
            "phone": phone,
            "body": " | ".join(bodies),
            "gv_number": group[0].get("gv_number", ""),
            "verdict": "ATTENTION",
            "reason": reason,
            "tier": "medium" if any(r.get("ask") for r in group) else "low",
            "ask": any(r.get("ask") for r in group),
            "money": None,
            "deadline": False,
            "_count": n,
            "_speakers": speakers[:5],
        })
    return kept, dropped


# ── scoring (mirrored by owner-queue.py; keep the two identical) ──────────
TIER_WEIGHT = {"critical": 1000, "high": 700, "medium": 400, "low": 150}


def score(item: dict) -> int:
    """Deterministic and explainable from the item alone."""
    s = TIER_WEIGHT.get(item.get("tier") or "medium", 400)
    seen = item.get("when")
    if seen is not None:
        age_h = max(0.0, (datetime.now(timezone.utc) - seen).total_seconds() / 3600.0)
        s += int(min(200, age_h / 6.0))
        if age_h < 24:
            s += 40
    if item.get("ask"):
        s += 80
    if item.get("deadline"):
        s += 60
    money = item.get("money")
    if isinstance(money, (int, float)) and money > 0:
        s += int(min(150, money / 10.0))
    if item.get("type") == "voicemail":
        s += 50
    return int(s)


# ── writing to the one queue table ────────────────────────────────────────
QUEUE_COLUMNS = (
    ("kind", "TEXT NOT NULL DEFAULT 'decision'"),
    ("channel", "TEXT"),
    ("party", "TEXT"),
    ("evidence_at", "TEXT"),
    ("evidence_ref", "TEXT"),
    ("dedupe_key", "TEXT"),
    ("meta_json", "TEXT"),
    ("seen_at", "TEXT"),
    ("last_score", "INTEGER"),
)


def ensure_columns(con) -> list[str]:
    have = {r[1] for r in con.execute("PRAGMA table_info(owner_decision_queue)")}
    added = []
    for name, decl in QUEUE_COLUMNS:
        if name not in have:
            con.execute("ALTER TABLE owner_decision_queue ADD COLUMN %s %s" % (name, decl))
            added.append(name)
    con.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_odq_dedupe "
        "ON owner_decision_queue(dedupe_key) WHERE dedupe_key IS NOT NULL")
    return added


def dedupe_key_for(it: dict) -> str:
    if it["type"] == "digest":
        return "gv:digest:%s:%s" % (
            it.get("phone") or it.get("name"), it.get("bucket") or it["day"])
    # Key on the MESSAGE, not the thread: two texts in one Gmail thread are two things
    # said, and keying on the thread made the second silently overwrite the first
    # (measured: 4 refreshes on the first backfill). A message id is stable across runs,
    # so a re-run still refreshes rather than duplicates.
    return "gv:%s:%s" % (it["type"], it.get("message_id") or it.get("thread_id") or it["iso"])


def _pretty_number(raw: str) -> str:
    """+12015667852 -> (201) 566-7852. A raw E.164 string is a number nobody can read off a card."""
    d = re.sub(r"[^0-9]", "", str(raw or ""))
    if len(d) == 11 and d.startswith("1"):
        d = d[1:]
    if len(d) == 10:
        return "(%s) %s-%s" % (d[:3], d[3:6], d[6:])
    return str(raw or "")


def title_for(it: dict) -> str:
    who = it.get("name") or it.get("phone") or "unknown"
    if it["type"] == "voicemail":
        return "Voicemail from %s: %s" % (who, it["body"][:150] or "(no transcript)")
    if it["type"] == "missed_call":
        n = it.get("_count") or 1
        return ("Missed call from %s" % who) if n == 1 else (
            "%d missed calls from %s" % (n, who))
    if it["type"] == "digest":
        n = it.get("_count") or 0
        speakers = it.get("_speakers") or []
        spoke = (" (%s)" % ", ".join(speakers[:4])) if len(speakers) > 1 else ""
        if it.get("phone") == "" and str(it.get("name") or "").startswith("unrecognised"):
            # "6 texts from unrecognised callers" would be a lie: these are CALLS, and the numbers
            # are the whole point of the row.
            return "%d missed call%s this week from numbers not in your contacts: %s" % (
                n, "" if n == 1 else "s", (it.get("body") or "")[:120])
        head = "%d text%s from %s%s" % (n, "" if n == 1 else "s", who, spoke)
        return head + (": " + it["body"][:110] if it.get("body") else "")
    return "Text from %s: %s" % (who, it["body"][:150])


def context_for(it: dict) -> str:
    lines = []
    if it.get("phone") and it.get("name"):
        lines.append("Number: %s" % it["phone"])
    if it.get("gv_number"):
        lines.append("Came in on: %s" % it["gv_number"])
    lines.append("When: %s" % it["iso"][:16].replace("T", " "))
    lines.append("Why it is in the queue: %s" % it.get("reason", ""))
    if it["body"]:
        lines.append("")
        lines.append(it["body"])
    return "\n".join(lines)


def write_items(con, queue_items: list[dict]) -> dict:
    """Upsert by dedupe_key. Never resurrects a dismissed/resolved row."""
    stats = {"new": 0, "refreshed": 0, "left_closed": 0}
    now_iso = datetime.now(timezone.utc).isoformat()
    for it in queue_items:
        key = dedupe_key_for(it)
        s = score(it)
        existing = con.execute(
            "SELECT id, status FROM owner_decision_queue WHERE dedupe_key=?", (key,)
        ).fetchone()
        is_decision = it.get("verdict") == "DECISION"
        severity = it.get("tier") or "medium"
        question = title_for(it)
        context = context_for(it)
        meta = json.dumps({"count": it.get("_count"), "speakers": it.get("_speakers"),
                           "type": it["type"], "account": it.get("account"),
                           "message_id": it.get("message_id"),
                           # The reader ranks from the row, so the terms it needs must live in the
                           # row. Without these a restart would silently lose the ask/deadline/money
                           # weighting and the order would quietly stop meaning what it says.
                           "ask": bool(it.get("ask")),
                           "deadline": bool(it.get("deadline")),
                           "money": it.get("money"),
                           "verdict": it.get("verdict"),
                           "reason": it.get("reason"),
                           "name_source": it.get("name_source")}, default=str)
        if existing:
            if existing[1] in ("pending",):
                con.execute(
                    "UPDATE owner_decision_queue SET question=?, context=?, severity=?,"
                    " last_score=?, evidence_at=?, meta_json=? WHERE dedupe_key=?",
                    (question, context, severity, s, it["iso"], meta, key))
                stats["refreshed"] += 1
            else:
                stats["left_closed"] += 1
            continue
        con.execute(
            "INSERT INTO owner_decision_queue"
            " (asked_at, question, context, severity, source, status, kind, channel,"
            "  party, evidence_at, evidence_ref, dedupe_key, meta_json, last_score)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (now_iso, question, context, severity,
             "gv-ingest:%s" % it["type"], "pending",
             "decision" if is_decision else "attention",
             it["type"], it.get("name") or it.get("phone"),
             it["iso"], it.get("message_id") or it.get("thread_id"), key, meta, s))
        stats["new"] += 1
    con.commit()
    return stats


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=2)
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--accounts", default=",".join(GV_ACCOUNTS))
    ap.add_argument("--explain", action="store_true", help="print verdicts, write nothing")
    ap.add_argument("--only-dropped", action="store_true")
    ap.add_argument("--verbose", action="store_true")
    a = ap.parse_args(argv)

    accounts = [x.strip() for x in a.accounts.split(",") if x.strip()]
    items, errors = fetch(accounts, a.days, a.verbose)
    if not items and errors:
        print("INGEST FAILED: no GV items read and %d error(s):" % len(errors))
        for e in errors[:5]:
            print("  " + e)
        return 1

    # A bare number is not actionable, and the corpus is full of them ("Missed call from
    # (848) 224"). The comms index already knows who these numbers are.
    resolved = resolve_names(items)
    queue_items, dropped = build_queue_items(items)

    if a.explain:
        print("fetched %d item(s) from %d account(s); %d -> queue, %d dropped"
              % (len(items), len(accounts), len(queue_items), len(dropped)))
        # The tally is the rule audit: it says how much each rule actually caught, so a rule
        # that fires on nothing (or on everything) is visible instead of plausible.
        tally: dict[str, int] = defaultdict(int)
        for d in dropped:
            reason = str(d.get("reason") or "")
            key = reason.split(":")[0].split("(")[0].strip()
            tally[key] += 1
        print("\n--- DROPPED BY RULE (%d) ---" % len(dropped))
        for reason, n in sorted(tally.items(), key=lambda kv: -kv[1]):
            print("  %4d  %s" % (n, reason))
        if a.only_dropped:
            print("\n--- DROPPED DETAIL (%d) ---" % len(dropped))
            for d in dropped:
                print("  [%s] %-24s %s :: %s" % (
                    d["type"], (d.get("name") or d.get("phone") or "?")[:24],
                    d["reason"], (d["body"] or "")[:70]))
        if not a.only_dropped:
            print("\n--- QUEUED (%d) ---" % len(queue_items))
            for q in sorted(queue_items, key=score, reverse=True):
                print("  %5d %-9s %-9s %-24s %s" % (
                    score(q), q["verdict"], q["tier"],
                    (q.get("name") or q.get("phone") or "?")[:24], title_for(q)[:95]))
        if errors:
            print("\n--- ERRORS (%d) ---" % len(errors))
            for e in errors[:10]:
                print("  " + e)
        return 0

    con = sqlite3.connect(a.db, timeout=180)
    con.row_factory = sqlite3.Row
    added = ensure_columns(con)
    stats = write_items(con, queue_items)
    # THE ARITHMETIC OF A COMPLETE READ, written down where health can check it. "18 rows arrived"
    # says nothing about the 62 items the run never saw; `fetched = queued + dropped` does, and
    # `unexplained` is the number that must always be zero.
    try:
        con.execute(
            "CREATE TABLE IF NOT EXISTS owner_queue_ingest_run ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL, ran_at TEXT NOT NULL,"
            " days INTEGER, fetched INTEGER, queued INTEGER, dropped INTEGER,"
            " new INTEGER, refreshed INTEGER, errors INTEGER, note TEXT)")
        con.execute(
            "INSERT INTO owner_queue_ingest_run (source, ran_at, days, fetched, queued, dropped,"
            " new, refreshed, errors, note) VALUES (?,?,?,?,?,?,?,?,?,?)",
            ("gv", datetime.now(timezone.utc).isoformat(), a.days, len(items),
             len(queue_items), len(dropped), stats["new"], stats["refreshed"], len(errors),
             (errors[0][:200] if errors else "")))
        con.commit()
    except Exception as exc:  # noqa: BLE001
        print("  (run arithmetic not recorded: %s: %s)" % (type(exc).__name__, exc))
    con.close()
    print("gv ingest: fetched=%d queued=%d dropped=%d new=%d refreshed=%d left_closed=%d"
          % (len(items), len(queue_items), len(dropped),
             stats["new"], stats["refreshed"], stats["left_closed"]))
    if added:
        print("  schema: added %s" % ", ".join(added))
    if errors:
        print("  %d error(s), first: %s" % (len(errors), errors[0]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
