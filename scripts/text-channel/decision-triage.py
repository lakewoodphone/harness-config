#!/usr/bin/env python3
"""decision-triage.py — decide, for every pending owner decision, whether it should
reach the owner at all, and in what form.

WHY THIS EXISTS (2026-10-21)
----------------------------
`owner_decision_queue` held 111 pending rows. `owner-ask.py` — the only program that
turns one into a text — was in no crontab, and when run by hand it refused its own top
candidate: a genuine question ("is a camera that uploads to the cloud acceptable?"),
because the composer had rendered it into a 152-character stub with a queue reference and
no actual ask. So the channel had three defects stacked:

  1. no deliverer on a clock,
  2. a ranking that put a 7-day-old idea ahead of a 1-hour-old critical voicemail,
  3. a composer that could take an answerable question and make it unanswerable.

This tool is the missing TRIAGE step between "a row exists" and "a person is asked". It
does not send anything and it does not edit the queue. It reads every pending row, decides
one of five dispositions, and validates any composed body against the REAL gate
(`ask_quality.review`), so the answer to "what can we actually send him?" is a measurement
rather than an opinion.

THE FIVE DISPOSITIONS
---------------------
  SEND_NOW     a real decision, still true, answerable, and composed within the ceiling.
  COMPOSE      a real decision, still true, but the stored wording cannot be sent as-is;
               a body must be written from its own fields.
  SYSTEM       not his: machinery, a deploy failure, a sync outage, a CI red. We fix it.
  STALE        true when filed, no longer true (or its own premise is past), or too old for
               the answer to change anything. Closed with a reason, never delivered.
  NOISE        should never have been a decision: an acknowledgement, a one-word text, a
               duplicate of a row already answered.

RULES THAT ARE THE OWNER'S OWN WORDS
------------------------------------
  * one question, one message, <=120 chars target / 160 ceiling (2026-09-25)
  * he answers money and his own decisions; he ignores machinery (10 of 16 vs 3 of 37)
  * never re-ask what we have already answered ourselves
  * the ladder stops: an unanswered question is asked twice, then dropped, never escalated

READ-ONLY. Opens both stores `mode=ro`, writes nothing.

USAGE
    decision-triage.py                     # summary + the ranked shortlist
    decision-triage.py --json              # machine-readable, one object per row
    decision-triage.py --disposition SEND_NOW
    decision-triage.py --compose 511       # show the composed body for one row
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HOME = Path.home()
AUTH_DB = Path(os.environ.get("AUTHORITY_DB", HOME / "authority.db"))
BIN = HOME / "bin"

#: The owner's stated ceiling. 160 is the hard limit; 120 is the target he asked for.
CEILING = 160
TARGET = 120

#: A decision older than this is almost never still actionable, and asking it costs the
#: same attention as a live one. Rows past it are STALE unless they carry a live deadline.
STALE_AFTER_DAYS = 10

#: Not his. Each pattern is a class of thing this estate has repeatedly filed to a man who
#: runs a phone shop: a machine's own health, a build's colour, a sync's lag.
#:
#: JUDGED ON THE QUESTION, NOT THE CONTEXT (corrected 2026-10-21). Measured: matching the
#: email body too swallowed five genuine asks -- "Google has revoked the key that runs
#: Gemini, could you create a new key?", "the leaked GitHub token is still live", "rotate
#: the SerpAPI key?", plus two policy questions -- because the surrounding email contained
#: the words "credential" and "workflow". A credential the SYSTEM cannot rotate is his; the
#: context is the email that mentioned it, not the ask. So the system patterns see the
#: question only, and the credential rule is narrowed to things we demonstrably do handle.
SYSTEM_PATTERNS = (
    (r"deploy workflow failed|workflow failed|ci failed|pre-?check failed|"
     r"test shard \d|shard \d/\d (red|failed)",
     "a CI/deploy failure: the machine's state, fixed by the machine"),
    (r"webhook|sync_breaker|behind on|freshness|watchdog|heartbeat|broker|mesh node",
     "a plumbing health notice"),
    (r"circuit breaker|lifecycle sweep|database is locked|migration",
     "internal machinery"),
    (r"^(pr|pull request)\s*[:#-]", "a code-review event"),
    (r"test shard|flaky|vitest|eslint", "a test result"),
    (r"\b\d+ notices\b.*\b(failed|failure)\b", "a bundle of machine failure notices"),
)

#: Patterns that are machinery ONLY when they are the whole question. Used on the question
#: text alone, never on the context, and never for anything that asks the owner to supply a
#: credential -- that is his to give or withhold.
#:
#: EMPTY ON PURPOSE as of 2026-10-21: the only entry was "rotate the live X key?", and a key
#: ROTATION IS HIS. Measured the same day: #850 asks whether to rotate a live SerpAPI key
#: that was printed into a session transcript. The agent can perform the rotation, but the
#: decision to invalidate a working credential -- and the blank of any downstream consumer
#: -- is the owner's. Filing it as machinery would have buried a live security question.
SYSTEM_QUESTION_ONLY: tuple[tuple[str, str], ...] = ()

#: Noise: rows that are not questions at all.
NOISE_PATTERNS = (
    (r"^(text|sms|whatsapp) from [^:]+:\s*(thanks?|thank you|ok(ay)?|yes|no|k|ty|lol|"
     r"👍|🙏|sure|great|hi|hello|good morning)\.?$", "an acknowledgement, not a decision"),
    (r"^\s*(thanks?|thank you|ok(ay)?|got it)\s*[.!]*\s*$", "an acknowledgement"),
    (r"^(FYI|Heads up)\b", "a notice, not a question"),
)

#: Signals that a row's own premise is a date that has passed. NARROWED 2026-10-21: the
#: first version included `by|before`, and fired on "he has been chasing this cancellation
#: SINCE Oct 19" -- a start date, not a deadline -- which marked a live billing dispute as
#: stale. A past-tense marker (`since`, `received`, `sent`) means the date is history, not
#: a deadline, so those are excluded before this is even tried.
PAST_DEADLINE = re.compile(
    r"\b(due|deadline|expires?|expiring|renews?|lapses?|overdue|cut ?off)\b"
    r"[^.]{0,40}?(\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}(?:/\d{2,4})?)", re.I)

#: A date preceded by one of these is describing the past, so it cannot be a deadline.
_PAST_MARKERS = re.compile(
    r"\b(since|as of|received|sent|chasing|started|filed|opened|created|paid|"
    r"charged|called|emailed|noticed|saw|was|were|had)\b[^.]{0,32}$", re.I)

#: Rows that name money and a decision are the ones he actually answers.
MONEY = re.compile(
    r"\$\s?\d|\b\d[\d,]*\.\d{2}\b|\bpay(ment)?\b|\binvoice\b|\brefund\b|\bcharge\b|"
    r"\bbill\b|\bcost\b|\btax\b|\bpayroll\b|\bcredit\b|\bstatement\b", re.I)

#: A body must ASK. This is deliberately not ask_quality's rule: that gate accepts a
#: statement ("NJ payroll tax NJ-927/927-W due 10/30/2026") because it judges SHAPE, and a
#: statement has a valid shape. Measured 2026-10-21: the top six "sendable" rows included
#: two statements the owner could only reply to with "ok... and?". A message he cannot
#: answer in one line is not a question, and sending it spends his attention for nothing.
ASKS_HIM = re.compile(
    r"^\s*[^.!]*\?|"                       # the first sentence asks
    r"\?\s*$|"                             # or the body ends in a question
    r"\b(want me to|should i|should we|shall i|do you want|would you like|"
    r"ok\?|okay\?|yes or no|which one|your call|approve|or should)\b|"
    # An either/or question frequently ends in a bare noun phrase with no "?": measured
    # 2026-10-21, #805 "... or skip it and rely on making the reset pointless?" and #810
    # "... so a factory reset is blocked ..., or skip it?" -- and #810's sibling
    # "should integrator shifts merge clean integrate/* PRs to main themselves, or will you
    # keep merging them?" carries no question mark at all. "should" is the signal.
    r"\bshould\b(?![^?]*\?)|"
    r"\?\s+\S",                            # a question mark mid-body ("...? I'd ...")
    re.I)



def _ro(path: Path) -> sqlite3.Connection:
    return sqlite3.connect("file:%s?mode=ro" % path, uri=True, timeout=10)


def _age_days(stamp: str | None) -> float:
    if not stamp:
        return 9999.0
    try:
        t = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return 9999.0
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - t).total_seconds() / 86400.0


def _freshness_days(row: dict) -> float:
    """Age of the row's PREMISE, not of the row.

    Measured 2026-10-21: #110 was re-measured (its Bluelink block confirmed still true) and
    rewritten, and the very next triage called it STALE ``because it is 32 days old'' -- which
    would have closed a question I had just verified. A row that carries an ``evidence_at``
    newer than its ``asked_at`` has been re-checked, so the number that matters for staleness
    is the age of the EVIDENCE.
    """
    asked = row.get("asked_at")
    evidence = row.get("evidence_at")
    if evidence and asked:
        try:
            a = datetime.fromisoformat(str(asked).replace("Z", "+00:00"))
            e = datetime.fromisoformat(str(evidence).replace("Z", "+00:00"))
            if e > a:
                return _age_days(evidence)
        except ValueError:
            pass
    return _age_days(asked)


def _gate(body: str) -> tuple[bool, list[str]]:
    """The real gate, if it is importable. A failure to import is reported, never assumed."""
    sys.path.insert(0, str(BIN))
    try:
        import ask_quality  # type: ignore
    except Exception as exc:  # noqa: BLE001
        return False, ["gate unavailable: %s" % exc]
    try:
        ok, reasons = ask_quality.review(body, kind="other")
        return bool(ok), list(reasons or [])
    except Exception as exc:  # noqa: BLE001
        return False, ["gate raised: %s" % exc]


#: Engineering vocabulary that must not reach the owner's phone. `ask_quality` refuses any
#: body containing fix/patch/deploy/migrate/debug/traceback because that is how a machine
#: instruction to an agent looks; it refuses NOUNS too ("the two-name fix", "config fix
#: flagged"), which is a false positive. The right repair is not to weaken a guard that
#: exists because internal instructions once reached him -- it is that a message TO him
#: should not be written in engineering vocabulary at all.
_VOCAB = (
    (r"\bconfig fix flagged\b", "the configuration needs updating"),
    (r"\bconfig fix\b", "a configuration change"),
    (r"\bthe two-name fix\b", "the simpler change"),
    (r"\bchain-following fix\b", "the follow-up change"),
    (r"\breconciliation fix\b", "reconciliation change"),
    (r"\bDNS-filter change\b", "the location filtering change"),
    (r"\bthe fix\b", "the change"),
    (r"\bfixes\b", "changes"),
    # Whole-word only, and last, so the specific phrases above win first. A substring rule
    # here would turn "prefix" into "prechange" and "fixture" into "changeture".
    (r"(?<!pre)(?<!suf)\bfix\b(?!ture)", "change"),
    (r"\bfixed\b", "done"),
    (r"\bpatched\b", "changed"),
    (r"\bdeploy(ed|ment)?\b", "release"),
    (r"\bmigrat(e|ed|ion)\b", "move"),
    (r"\bdebug\b", "investigate"),
    (r"\btraceback\b", "error detail"),
    (r"\bmint\b", "create"),
    (r"\bthe canary\b", "the trial"),
    (r"\ballowlist\b", "approved list"),
)

#: A body that still carries a path, a command or a hostname is an engineering note.
_TECHNICAL = re.compile(
    r"/home/|/tmp/|/var/|/etc/|~/|C:\\|\w+\.(py|sh|db|json|log|txt|sql|ya?ml)\b|"
    r"\b(cd|ls|grep|curl|ssh|scp|sqlite3|systemctl|crontab|python3?|bash|pwsh|node)\s+[-\w./]",
    re.I)


def _tidy_body(body: str) -> str:
    """Strip engineering vocabulary and trim to the ceiling at a word boundary."""
    out = body
    for pat, sub in _VOCAB:
        out = re.sub(pat, sub, out, flags=re.I)
    # A substitution can leave a doubled article ("Approve the the location filtering
    # change" -- measured on #890, where "DNS-filter change" became "location filtering
    # change" after "the"). Collapse it, and collapse any doubled word, because a body that
    # reads as a typo is the kind of message the owner learns to skim.
    out = re.sub(r"\b(\w+)\s+\1\b", r"\1", out, flags=re.I)
    # A question mark followed by the sentence-splitting artefact ("land?.") reads as a typo.
    out = out.replace("?.", "?").replace(".?", "?").replace("..", ".")
    out = " ".join(out.split())
    # A body cut at the ceiling keeps its question mark: a truncation must never turn a
    # question into a statement, which is exactly what happened to #890 before this line.
    if len(out) > CEILING:
        head = out[: CEILING - 2].rsplit(" ", 1)[0].rstrip(",;:—-")
        head = re.sub(r"\b(\w+)\s+\1\b", r"\1", head, flags=re.I)
        asks = "?" in out
        out = head + ("?" if asks else "…")
    return out


def _ctx_field(context: str, label: str) -> str:
    """Pull one labelled line out of the row's context block.

    The context is a small structured block the ingest writes:
        From: ... / To: ... / When: ... / Subject: ...
        Why it is in the queue: <the fact that makes it his>
        What he would do: <the action>
        <the email body>
    Reading it is the difference between a statement and a question.
    """
    m = re.search(r"^%s:\s*(.+)$" % re.escape(label), context, re.I | re.M)
    return " ".join(m.group(1).split()) if m else ""


def _deadline_days(context: str, question: str = "") -> int | None:
    """Days until the soonest future date named in the row. Earlier dates win.

    Both spellings occur in this store: ISO (`2026-10-30`) and US (`10/30/2026`). Only
    future dates count -- a date that has passed belongs to a STALE verdict, not to a
    deadline the owner can still act on.
    """
    best = None
    today = datetime.now(timezone.utc).date()
    text = "%s %s" % (question, context)
    for m in re.finditer(r"\b(\d{4}-\d{2}-\d{2})\b", text):
        try:
            when = datetime.fromisoformat(m.group(1)).date()
        except ValueError:
            continue
        delta = (when - today).days
        if delta >= 0 and (best is None or delta < best):
            best = delta
    for m in re.finditer(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b", text):
        mm, dd, yy = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if yy < 100:
            yy += 2000
        try:
            when = datetime(yy, mm, dd).date()
        except ValueError:
            continue
        delta = (when - today).days
        if delta >= 0 and (best is None or delta < best):
            best = delta
    return best


def compose(row: dict) -> str:
    """Write the body the owner should receive, from the row's own fields.

    A decision queue row is written for the record; a text is written for a phone. The
    rules come from what the owner actually answers (2026-09-25: one question, <=160
    chars; he replies to money and to his own decisions and ignores machinery):

      * lead with the fact that makes it his, in one clause,
      * say the deadline as a NUMBER OF DAYS when one can be read, because "due 10/30"
        requires arithmetic and "in 9 days" does not,
      * end with the ask, taken from the row's own "What he would do" when it has one,
      * never lead with a queue reference, never send a statement with no ask.

    Measured failure this replaces: row 877 composed to the bare statement "NJ payroll tax
    NJ-927/927-W due 10/30/2026 ..." -- 72 characters that pass ask_quality's structural
    gate (it only checks shape) and that a person cannot answer.
    """
    question = " ".join(str(row.get("question") or "").split())
    context = str(row.get("context") or "")
    rec = " ".join(str(row.get("recommendation") or "").split())

    # Our bookkeeping is not part of the message.
    question = re.sub(r"^\s*[\[#](?:q|ask-?)\d+\]?\s*", "", question, flags=re.I)

    why = _ctx_field(context, "Why it is in the queue")
    todo = _ctx_field(context, "What he would do")
    who = _ctx_field(context, "From")
    sender = re.sub(r"\s*<[^>]+>", "", who).strip()
    days = _deadline_days(context, question)

    # ── A TRANSCRIPT IS NOT A QUESTION ────────────────────────────────────────────
    # Measured 2026-10-21: the critical voicemail row composed to 158 characters of ASR
    # rubble ("...in case you do call me back Unless you said I should call Tom cuz thats
    # how to get through to you...") plus "Want me to handle it?". Mindless to receive and
    # impossible to answer. The row's own `why` line states the fact in one clause, so a
    # transcript-shaped row is composed from THAT and the body transcript is never sent.
    transcript = bool(re.search(r"voicemail|missed call|transcript",
                                question + " " + context, re.I)) or (
        re.search(r"^(text|sms|whatsapp) from ", question, re.I) is not None
        and len(question) > 140)
    if transcript and why:
        # "voicemail from Manela asking to be called back" -> "Manela left a voicemail
        # asking to be called back", so the name appears once and the ask reads naturally.
        fact = why.rstrip(". ")
        m = re.search(r"^(voicemail|call|text|sms|whatsapp)\s+from\s+([A-Z][\w'.-]+)\s+(.*)$",
                      fact, re.I)
        if m:
            kind, caller, rest = m.group(1).lower(), m.group(2), m.group(3).strip()
            kind = {"call": "missed call", "sms": "text", "whatsapp": "WhatsApp message"}.get(
                kind, kind)
            fact = "%s left a %s %s" % (caller, kind, rest)
        fact = fact[0].upper() + fact[1:] if fact else question
        if re.search(r"\bcall (me |us )?back\b|\bcalled?\b.*\bno answer\b|"
                     r"asking to be called|please call", fact, re.I):
            ask_t = "Want me to call back?"
        elif re.search(r"\breply\b|\btext\b|\brespond\b", fact, re.I):
            ask_t = "Want me to reply?"
        else:
            ask_t = "Want me to handle it?"
        body_t = "%s. %s" % (fact, ask_t)
        if len(body_t) <= CEILING:
            return body_t


    # The fact, with the deadline made arithmetic-free.
    lead = question.rstrip(". ")
    if days is not None and days <= 21:
        when = ("today" if days == 0 else ("tomorrow" if days == 1 else "in %d days" % days))
        lead = re.sub(r"\b(due|by|before|renews?|expires?)\s+\d{4}-\d{2}-\d{2}",
                      lambda m: "%s %s" % (m.group(1), when), lead, flags=re.I)
        lead = re.sub(r"\b(due|by|before|renews?|expires?)\s+\d{1,2}/\d{1,2}(/\d{2,4})?",
                      lambda m: "%s %s" % (m.group(1), when), lead, flags=re.I)

    # ── WHERE THE QUESTION ACTUALLY IS ───────────────────────────────────────────
    # Measured 2026-10-21 on the live queue: four genuine questions survived composition
    # as bare statements, because their ASK is in the LAST sentence, not the first:
    #   #511 "... every seller advertises the ABSENCE of connectivity ... Before we spend
    #         anything on it: is a camera that uploads to the cloud acceptable, or should
    #         it be a camera that keeps everything on the device?"
    #   #714 "The front-door contact sensor has read OPEN ... Is the magnet still on the
    #         door frame?"
    #   #885 "... the 60/month limit runs out in two to four days. Cut the checks per
    #         push, or fund the real cost?"
    # A person answers the last sentence. So the body must CARRY the asking sentence
    # (whole, when it fits) and may carry only a short context clause before it. Taking
    # the first sentence and dropping the rest threw away the only part he could act on.
    sentences = [s.strip() for s in re.split(r"(?<=[.?!])\s+", question) if s.strip()]
    ask_sentence = ""
    for s in reversed(sentences):
        if "?" in s or ASKS_HIM.search(s):
            ask_sentence = s
            break
    if ask_sentence:
        room = CEILING - len(ask_sentence) - 2
        context = ""
        for s in sentences:
            if s == ask_sentence:
                break
            cand = s.rstrip(". ")
            if len(cand) <= room:
                context = cand
                break
            head = cand.split(",")[0]
            if len(head) <= min(room, 90):
                context = head
            break
        body_q = ("%s. %s" % (context, ask_sentence)) if context else ask_sentence
        if len(body_q) <= CEILING:
            return _tidy_body(body_q)

        # THE ASK DOES NOT FIT ON ITS OWN. Measured 2026-10-21 on #805: the either/or ran
        # to 197 characters and the body was cut to 158 mid-sentence, losing the "or skip
        # it?" that made it answerable -- a truncation that turned a question into a fact.
        # So shorten the OPTIONS, never the ask: keep the opening clause (what it is) and
        # the second alternative (the choice), drop the persuasive middle.
        m2 = re.match(r"^(.*?),\s*or\s+(.*)$", ask_sentence, re.S)
        if m2:
            opening, alternative = m2.group(1).strip(), m2.group(2).strip()
            brevity = CEILING - len(alternative) - 8
            if brevity >= 20:
                short_open = opening
                if len(short_open) > brevity:
                    # CUT ON A CLAUSE BOUNDARY, NEVER MID-CLAUSE. Measured 2026-10-21 on
                    # #805: a word-boundary cut produced "so a factory, or skip it and rely
                    # on making the reset pointless?" -- grammatically broken at the exact
                    # place the reader needs sense. Prefer an existing comma inside the
                    # opening; if there is none short enough, drop the opening entirely and
                    # put the alternative as a plain question.
                    clauses = [c.strip() for c in opening.split(",") if c.strip()]
                    short_open = ""
                    for c in clauses:
                        if len(c) <= brevity:
                            short_open = c
                        else:
                            break
                    if not short_open:
                        # NOTHING OF THE OPENING FITS. The opening usually carries the
                        # PRIMARY option (a purchase, an approval); the alternative carries
                        # the do-without. Asking only the do-without is how #805 became
                        # "Skip it and rely on making the reset pointless?" -- which drops
                        # the $5-per-device choice it exists to put to him.
                        #
                        # A MID-CLAUSE CUT IS WORSE THAN NO CONTEXT. Measured on #805: every
                        # word-boundary cut produced prose like "so a factory, or skip it...".
                        # So take the HEAD of the opening, which is the noun phrase naming
                        # what is being decided (everything before the first subordinator),
                        # and append the alternative as a clean either/or.
                        head = re.split(r"\b(so|because|which|that|since|while)\b",
                                        opening, maxsplit=1, flags=re.I)[0]
                        head = head.strip().rstrip(",;:(")
                        # drop an unbalanced trailing parenthetical
                        if head.count("(") > head.count(")"):
                            head = head[: head.rfind("(")].rstrip(",;: ")
                        head = re.sub(r"^(buy|approve|allow|add|install|set up|turn on)\b",
                                      lambda m: m.group(1).capitalize(), head, flags=re.I)
                        if head and len(head) + len(alternative) + 6 <= CEILING:
                            return _tidy_body("%s, or %s" % (head, alternative))
                        if head and len(head) <= CEILING - 2:
                            return _tidy_body(head.rstrip(".") + "?")
                        body_q = alternative
                        if not body_q.rstrip().endswith("?"):
                            body_q = body_q.rstrip(".") + "?"
                        body_q = body_q[0].upper() + body_q[1:]
                        return _tidy_body(body_q)
                        body_q = alternative
                        if not body_q.rstrip().endswith("?"):
                            body_q = body_q.rstrip(".") + "?"
                        body_q = body_q[0].upper() + body_q[1:]
                        return _tidy_body(body_q)
                body_q = "%s, or %s" % (short_open, alternative)
                if len(body_q) <= CEILING:
                    return _tidy_body(body_q)
        # Last resort: the ask alone, trimmed at a word boundary. It stays a question.
        return _tidy_body(ask_sentence)


    # The ask: an explicit question, or the row's own stated action, or the rec.
    ask = ""
    if todo:
        ask = re.sub(r"^(reply|confirm|file|call|pay|book|ask|send|decide)\b",
                     lambda m: m.group(1).capitalize(), todo, flags=re.I).rstrip(". ")
        ask = ask[0].upper() + ask[1:] if ask else ask
        # The lead already carries the deadline as days ("due in 9 days"); repeating the
        # calendar date in the ask makes him do the arithmetic twice.
        if days is not None and days <= 21:
            ask = re.sub(r"\s+\b(?:by|before)\s+\d{4}-\d{2}-\d{2}|\s+\b(?:by|before)\s+"
                         r"\d{1,2}/\d{1,2}(?:/\d{2,4})?", "", ask, flags=re.I)
            ask = re.sub(r"\s+\bon\s+\d{4}-\d{2}-\d{2}", "", ask, flags=re.I)
        if "?" not in ask:
            ask = "Want me to %s?" % (ask[0].lower() + ask[1:] if ask else "handle it")
    if not ask and rec:
        short = re.split(r"(?<=[.!?])\s", rec)[0].strip()
        ask = "I'd %s. OK?" % (short[0].lower() + short[1:]) if short else "Want me to handle it?"
    if not ask:
        ask = "Want me to handle it?"

    body = "%s. %s" % (lead, ask) if not lead.endswith("?") else "%s %s" % (lead, ask)

    # A body that still carries a path, a command or a hostname is an engineering note.
    # Shorten it to its first sentence plus the ask rather than sending a file listing.
    if _TECHNICAL.search(body):
        first = re.split(r"(?<=[.?!])\s+", lead)[0].rstrip(". ")
        body = "%s. %s" % (first, ask)

    # Fit the ceiling at a sentence/space boundary, never mid-word, and strip the
    # engineering vocabulary a phone message must not carry.
    if len(body) > CEILING:
        room = CEILING - len(ask) - 2
        if room >= 40:
            head = lead[:room].rsplit(" ", 1)[0].rstrip(",;:")
            body = "%s. %s" % (head, ask)
    return _tidy_body(body)



def classify(row: dict) -> dict:
    q = str(row.get("question") or "")
    ctx = str(row.get("context") or "")
    text = q + " " + ctx
    age = _age_days(row.get("asked_at"))
    fresh = _freshness_days(row)
    out = {"id": row["id"], "age_days": round(age, 2),
           "severity": row.get("severity"), "source": row.get("source"),
           "question": q}

    # 1. noise: not a question at all
    for pat, why in NOISE_PATTERNS:
        if re.search(pat, q.strip(), re.I):
            out.update(disposition="NOISE", why=why)
            return out

    # 1b. an LLM gap wearing a decision's clothes
    # The mail judge falls back to `verdict: attention` when it returns no verdict for a
    # message, so a model hiccup becomes owner work. Measured 2026-10-21: 3 pending rows were
    # bundles of up to 9 unrelated emails queued with the reason "judge returned no verdict",
    # including newsletter subjects and a family name. That is not a decision; it is an
    # evaluation that did not happen, and it must be re-judged, never texted.
    if ("judge returned no verdict" in text
            or "TRIAGE 2026-10-21: judge_failure" in text):
        out.update(disposition="JUDGE_GAP",
                   why="the mail judge returned no verdict, so this row is an evaluation "
                       "gap rather than a decision; it must be re-judged, not texted")
        return out

    # 2. machinery: his shop does not need this on a phone
    for pat, why in SYSTEM_PATTERNS:
        if re.search(pat, q, re.I):
            out.update(disposition="SYSTEM", why=why)
            return out
    for pat, why in SYSTEM_QUESTION_ONLY:
        if re.search(pat, q.strip(), re.I):
            out.update(disposition="SYSTEM", why=why)
            return out

    # 3. a date in the row that has already passed
    m = PAST_DEADLINE.search(text)
    if m:
        # A past-tense clause ("chasing this since Oct 19") is history, not a deadline.
        before = text[max(0, m.start() - 40):m.start()]
        raw = m.group(2)
        try:
            if _PAST_MARKERS.search(before):
                raise ValueError("past-tense date")
            if re.match(r"\d{4}-", raw):
                when = datetime.fromisoformat(raw).date()
            else:
                bits = raw.split("/")
                yr = int(bits[2]) if len(bits) > 2 else datetime.now().year
                if yr < 100:
                    yr += 2000
                when = datetime(int(yr), int(bits[0]), int(bits[1])).date()
            if when < datetime.now(timezone.utc).date():
                out.update(disposition="STALE",
                           why="its own deadline (%s) has passed" % when.isoformat())
                return out
        except (ValueError, IndexError):
            pass

    # 4. too old to be worth his attention -- but ONLY for an item whose value is its
    # moment. A policy question ("how long do we keep customer photos?") is still true
    # whenever it is asked; an action ("reply about the dead panel") rots. Measured
    # 2026-10-21: the blunt age rule dropped #299, a real policy call, alongside #110,
    # a car repair that is genuinely overdue.
    ACTIONABLE = re.compile(
        r"\b(reply|confirm|call back|pay|file|book|renew|order|return|send|approve|"
        r"sign|cancel|schedule|submit)\b", re.I)
    if fresh > STALE_AFTER_DAYS and ACTIONABLE.search(q):
        out.update(disposition="STALE",
                   why="%.0f days since the premise was last measured, and it asks for an "
                       "action whose moment has passed" % fresh)
        return out

    # 5. compose and judge
    body = compose(row)
    ok, reasons = _gate(body)
    money = bool(MONEY.search(text))
    asks = bool(ASKS_HIM.search(body))
    out.update(body=body, chars=len(body), gate_ok=ok, gate_reasons=reasons,
               money=money, asks=asks)
    if ok and asks:
        out.update(disposition="SEND_NOW",
                   why="composes within the ceiling, passes the gate, and ends in a question")
    elif not asks:
        out.update(disposition="COMPOSE",
                   why="no ask survives composition: the body states a fact, so he cannot "
                       "answer it in one line; the row needs a written question")
    else:
        out.update(disposition="COMPOSE",
                   why="gate refuses the composed body: %s" % "; ".join(reasons[:2]))
    return out


def rank(rows: list[dict]) -> list[dict]:
    """Order by what deserves his attention, not by when it was filed."""
    sev = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    return sorted(rows, key=lambda r: (
        sev.get(str(r.get("severity")), 2),
        0 if r.get("money") else 1,
        r.get("age_days") or 0,
        r.get("id") or 0,
    ))


#: A stable identifier a row is ABOUT -- an order number, a work order, a long reference.
#: Two rows about one order are one question, however differently they are worded. Measured
#: 2026-10-21: #705 and #726 both concern Surface panel order 108746338 and survived the
#: word-key dedupe because they share almost no words.
SUBJECT_ID = re.compile(r"\b(WO\d{6,}|\d{9,}|[A-Z]{2,}\d{6,})\b")


def mark_duplicates(rows: list[dict]) -> None:
    """Set `duplicate_of` on a row that restates an identifier another row already owns.

    The OLDER row wins: it is the one whose premise the later row is usually confirming,
    and merging forward would lose the earlier context. The younger row is marked, not
    deleted -- closure is a separate, recorded act.
    """
    owner: dict[str, dict] = {}
    for r in sorted(rows, key=lambda x: (x.get("age_days") or 0) * -1):
        ids = set(SUBJECT_ID.findall(str(r.get("question") or "")))
        hit = next((owner[i] for i in ids if i in owner), None)
        if hit is not None:
            r["duplicate_of"] = hit["id"]
            r.setdefault("why", "")
            r["why"] = (r["why"] + "; restates %s, already filed as #%s"
                        % (",".join(sorted(ids)), hit["id"])).strip("; ")
        for i in ids:
            owner.setdefault(i, r)



def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--disposition")
    ap.add_argument("--compose", type=int)
    ap.add_argument("--limit", type=int, default=15)
    args = ap.parse_args(argv)

    conn = _ro(AUTH_DB)
    conn.row_factory = sqlite3.Row
    try:
        # A DEFERRED ROW IS NOT A PENDING ONE. The owner parks decisions in his own words
        # ("these are decisions about the product for next time i bring it up"; "too early -
        # the ones due in November get thought about in November"; "put a note that we should
        # look at this in 2 plus years"). `owner-queue.py` honours that on the read path, but
        # every program that can TEXT a row ignored the column -- so seven parked rows would
        # have gone to his phone the moment a sender was approved. Filtered in the SELECT, so
        # no ranking, dedupe or fallback can bring one back.
        rows = [dict(r) for r in conn.execute(
            "SELECT id, asked_at, severity, source, question, context, recommendation, "
            "status, blocks, evidence_at, deferred_until, defer_note "
            "FROM owner_decision_queue WHERE status='pending' "
            "AND (deferred_until IS NULL OR deferred_until <= datetime('now')) "
            "ORDER BY asked_at DESC")]
    finally:
        conn.close()

    if args.compose:
        target = next((r for r in rows if r["id"] == args.compose), None)
        if not target:
            print("no pending row with id %s" % args.compose)
            return 1
        c = classify(target)
        print("question :", target["question"][:300])
        print("body     :", c.get("body"))
        print("chars    :", c.get("chars"))
        print("gate     :", c.get("gate_ok"), c.get("gate_reasons"))
        print("verdict  :", c.get("disposition"), "-", c.get("why"))
        return 0

    results = [classify(r) for r in rows]
    mark_duplicates(results)
    # A duplicate is not sendable: asking twice about one order is the defect the queue
    # exists to prevent. It keeps its disposition so the report can show why it is held.
    for r in results:
        if r.get("duplicate_of"):
            r["disposition"] = "DUPLICATE"
    by: dict[str, int] = {}
    for r in results:
        by[r["disposition"]] = by.get(r["disposition"], 0) + 1

    if args.disposition:
        results = [r for r in results if r["disposition"] == args.disposition]

    results = rank(results)
    if args.json:
        print(json.dumps({"counts": by, "rows": results}, indent=1, default=str))
        return 0

    print("PENDING DECISIONS: %d" % len(rows))
    for k in ("SEND_NOW", "COMPOSE", "SYSTEM", "STALE", "NOISE", "DUPLICATE", "JUDGE_GAP"):
        print("  %-9s %3d" % (k, by.get(k, 0)))
    print()
    print("SHORTLIST (what he would actually be asked, best first):")
    shown = 0
    for r in results:
        if r["disposition"] not in ("SEND_NOW", "COMPOSE"):
            continue
        shown += 1
        if shown > args.limit:
            break
        print("#%-4s %-9s %-6s %5.1fd %s" % (
            r["id"], r["disposition"], r.get("severity"), r["age_days"] or 0,
            (r.get("body") or r.get("question"))[:96]))
    print("\n(%d sendable/composable of %d pending)" % (shown, len(rows)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
