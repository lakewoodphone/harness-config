#!/usr/bin/env python3
"""FLAG SOURCE: is the owner's text channel being spent on messages worth his attention?

THE SIGNAL
----------
Every OUTBOUND text to the owner (`+18483897895`) in the last window, read from the AI text
channel store, classified. The channel exists for three things and nothing else:

    QUESTION  one question only he can answer, carrying the evidence we already gathered
    RESULT    the outcome of work he asked for, naming the thing and the answer
    ALERT     something is broken and needs him

Everything else is NOISE: an acknowledgement ("Got it - filed as housekeeping#392."), an
internal machine instruction ("On the desktop (ZABZ-YOGA) run scripts/finance/…"), a test
string ("This is the turn-ledger probe; if you see this, the gate failed."), a promise in
place of work ("Let me pull the current state…"), or the same sentence sent twice.

WHY THIS SOURCE EXISTS, measured on the authority
-------------------------------------------------
    2026-10-02 18:58  the owner: "You could do a little more research before you ask the
                      questions … why do you even have to ask me … you could've googled it"
    2026-10-02 19:00  he is answered with "Got it - filed as housekeeping#392."
    2026-10-02 17:00  he is sent "[q1790960402] Amazon order history in the ledger is stale
                      (newest order 2026-09-10). On the desktop (ZABZ-YOGA) run" -- a machine
                      instruction, texted to a person
    2026-10-01 15:05  the SAME Home Depot question was put to him a second time, sixteen hours
                      after the first: "You literally sent me this text earlier."

In the 24 h to 2026-10-02 19:30Z that is 3 noise bodies and 1 repeated pair. The healthy
value is ZERO of each: a noise message has no reader who can act on it, and every one of them
spends the channel he has to trust for the ones that matter.

THRESHOLDS, and why these are abnormal
--------------------------------------
    noise >= 3 in the window (default 24 h)   measured 3 on 2026-10-02; healthy 0
    repeats >= 2 identical bodies            measured 1 on 2026-10-01; healthy 0
Both are env-overridable (`QNOISE_MAX`, `QNOISE_REPEAT_MAX`, `QNOISE_WINDOW_HOURS`). The
threshold is a floor, not a target: this source is the instrument that keeps the outbound gate
(`bin/textsend.py`) honest after it lands, and it must go quiet when the channel is clean.

SUBJECT   owner-question-noise:<utc-day> -- one session per day at most, however loud the day is.

MUST NEVER
    - send anything to anyone, or write the store (read-only, always);
    - fire on a body that is a real question, result or alert;
    - treat a missing store as health -- an unreadable signal prints the reason on stderr and
      exits 1.
"""
from __future__ import annotations

import os
import re
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _flag  # noqa: E402
from _flag import Finding, Unreadable  # noqa: E402

SOURCE = "owner-question-audit"
OWNER = os.environ.get("QNOISE_OWNER", "+18483897895")
WINDOW_HOURS = int(os.environ.get("QNOISE_WINDOW_HOURS", "24"))
NOISE_MAX = int(os.environ.get("QNOISE_MAX", "3"))
REPEAT_MAX = int(os.environ.get("QNOISE_REPEAT_MAX", "2"))
COOLDOWN_SECONDS = int(os.environ.get("QNOISE_COOLDOWN", "21600"))  # 6 h

# --- the classification, as data so it can be argued with rather than guessed at ----------
ACK = re.compile(
    r"^\s*(got it|got it[.,!]?\s*(thanks|thank you)?|understood|remembered|noted|captured|"
    r"will do|i'?m on it|i am on it|on it|sure|ok(ay)?|done|thanks|thank you|"
    r"filed as|no problem)\b", re.I)
ACK_MAX_CHARS = 120
FILED_REF = re.compile(r"filed as\s+\w+#\d+|housekeeping#\d+", re.I)
INTERNAL = re.compile(
    r"\[q\d{6,}\]|#ask-\d+|on the desktop|zabz-yoga|zabz-tech|\bscripts?/[a-z0-9_./-]+|"
    r"(^|\s)(~/|/home/|c:\\\\)|\.py\b|\.sh\b|ledger is stale|in the ledger is stale|"
    r"\bre-?run\b|\brun the\b|\bcron\b|\bwake #\d+|\bsid\b|SM[0-9a-f]{32}", re.I)
PROBE = re.compile(r"probe|selftest|if you see this|gate failed|test message|"
                   r"dry run|ignore this", re.I)
PROMISE = re.compile(
    r"^\s*(let me\b|i'?ll (look|pull|check|go|dig|start|get)\b|i will (look|pull|check|go|dig|"
    r"start|get)\b|starting (now|the)\b|working on it\b|i'?m (looking|checking|on it)\b)", re.I)

# A question mark alone is not a question: an ack can carry one ("Filed it - anything else?").
# The gate is: it asks something AND it is not one of the noise shapes above. `ASK` catches the
# imperative form the CFO composer uses -- "Reply 'yes' - or tell me what it was and I'll file
# it for good" is a question even though it ends without a mark (measured 2026-10-02).
ASK = re.compile(r"\breply\b|\btell me\b|\bsay (yes|no|what)\b|\bconfirm\b|\bdo you want\b|"
                 r"\blet me know\b", re.I)
QUESTION = re.compile(r"\?|^(what|which|where|when|who|why|how|did|do|does|is|are|can|could|"
                      r"would|should|will)\b", re.I)


def _gate_deployed_at():
    """When the outbound gate went in, if it is in the live sender now -- else None.

    WHY THIS EXISTS (measured 2026-10-02, the night the gate was deployed): the window is 24 h, so
    on the first run after the deploy this source still saw the day's noise that the gate had just
    been built to stop, and it filed a repair flag for work already in flight. That is the same
    defect as a monitor that fires on the healthy case. So once `classify_owner_body` is present in
    textsend.py, the window starts at THAT FILE'S OWN mtime: the instrument measures the channel the
    gate is protecting, not the history it was built to end. Before the gate exists, the full window
    applies, because then the noise is the live state of the system.
    """
    p = Path(os.environ.get("AITEXT_SEND") or (Path.home() / "bin" / "textsend.py"))
    try:
        if "def classify_owner_body" not in p.read_text(encoding="utf-8", errors="replace"):
            return None
        return datetime.fromtimestamp(p.stat().st_mtime, timezone.utc)
    except Exception:  # noqa: BLE001 -- an unreadable sender is not a reason to fire
        return None


def _store() -> Path:
    return Path(os.environ.get("SMS_INBOX_DB") or (Path.home() / ".sms-inbox" / "inbox.db"))


def _normalise(body: str) -> str:
    return re.sub(r"\s+", " ", (body or "").strip().lower())[:400]


#: A periodic report is not noise. The morning/evening briefings are a standing product the
#: owner asked for; classifying them here would make this source fire on the healthy case,
#: which its own header forbids. Measured 2026-10-02: 5 briefing bodies in the store.
DIGEST = re.compile(r"briefing|digest|daily summary|status report", re.I)


def classify(body: str) -> str:
    """QUESTION | RESULT | ALERT | NOISE. Pure, so the replay harness tests the same function."""
    text = (body or "").strip()
    if not text:
        return "NOISE"
    # An alert is checked FIRST, on a leading marker only: "🔴 URGENT — CEO needs a decision"
    # must not fall through to NOISE just because its body mentions a path or a task id.
    if re.match(r"^\s*(🔴|🚨|⚠️|❗|urgent\b|alert\b|incident\b)", text, re.I):
        return "ALERT"
    if DIGEST.search(text[:400]):
        return "RESULT"
    if PROBE.search(text):
        return "NOISE"
    if INTERNAL.search(text):
        return "NOISE"
    if FILED_REF.search(text):
        return "NOISE"
    if len(text) <= ACK_MAX_CHARS and ACK.match(text):
        return "NOISE"
    if len(text) <= 200 and PROMISE.match(text) and not re.search(r"\d", text):
        return "NOISE"
    if QUESTION.search(text) or ASK.search(text):
        return "QUESTION"
    return "RESULT"


def collect(args) -> list[Finding]:
    path = _store()
    if not path.is_file():
        raise Unreadable("the text channel store does not exist at %s" % path)
    since = datetime.now(timezone.utc) - timedelta(hours=WINDOW_HOURS)
    gate_at = _gate_deployed_at()
    clamped = False
    if gate_at is not None and gate_at > since:
        since, clamped = gate_at, True
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=15)
        con.row_factory = sqlite3.Row
        # The window is measured on `first_seen`, which this store always writes as ISO-8601.
        # `date_sent` is NOT safe for that comparison: it also carries Twilio's RFC-822 form
        # ("Fri, 25 Sep 2026 …"), and as a string that sorts after every ISO date, so a window
        # filter on it silently pulls in months-old rows (measured 2026-10-02: 40 rows from
        # June/July appeared inside a September window).
        rows = con.execute(
            "SELECT sid, body, status, coalesce(date_sent, first_seen) AS at, first_seen FROM messages "
            "WHERE direction='outbound' AND to_number=? AND first_seen >= ? "
            "ORDER BY first_seen DESC",
            (OWNER, since.isoformat()),
        ).fetchall()
        con.close()
    except Exception as exc:  # noqa: BLE001
        raise Unreadable("could not read %s: %s" % (path, exc))

    # A body the provider REFUSED never reached him, so it is not a message he had to read.
    # Measured 2026-09-25 (`P2819`): 40+ reminder texts in an hour, none delivered, and counting
    # them as attention spent would make this source fire on an outage instead of on noise.
    delivered = [r for r in rows if (r["status"] or "").lower() not in ("failed", "undelivered")]
    undelivered = len(rows) - len(delivered)

    noise, counts, seen = [], {"QUESTION": 0, "RESULT": 0, "ALERT": 0, "NOISE": 0}, {}
    for r in delivered:
        body = r["body"] or ""
        kind = classify(body)
        counts[kind] += 1
        if kind == "NOISE":
            noise.append({"at": r["at"], "sid": r["sid"], "body": body[:200]})
        key = _normalise(body)
        if key:
            seen.setdefault(key, []).append(r["sid"])
    repeats = {k: v for k, v in seen.items() if len(v) >= REPEAT_MAX}

    if len(noise) < NOISE_MAX and len(repeats) < REPEAT_MAX:
        return []
    window_note = ("the window is measured from when the outbound gate was deployed (%s) and NOT "
                   "from %d h ago: noise the gate was built to stop is not charged to the gate"
                   % (gate_at.isoformat(timespec="seconds"), WINDOW_HOURS)) if clamped else \
                  ("the window is the last %d h" % WINDOW_HOURS)

    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    examples = "\n".join("        %s  %s" % (n["at"], n["body"].replace("\n", " / ")[:96])
                         for n in noise[:6]) or "        (none)"
    repeat_lines = "\n".join("        x%d  %s" % (len(v), k[:96]) for k, v in list(repeats.items())[:4]) \
        or "        (none)"

    prompt = (
        "THE OWNER'S TEXT CHANNEL IS BEING SPENT ON MESSAGES THAT ARE NOT WORTH HIS ATTENTION.\n\n"
        "MEASURED (%s, %s, source: %s)\n"
        "    outbound bodies that REACHED him: %d   QUESTION %d · RESULT %d · ALERT %d · NOISE %d\n"
        "    a further %d outbound row(s) were written but not delivered, so they are not counted\n"
        "    his words, 2026-10-02 18:58: \"You could do a little more research before you ask the\n"
        "    questions … why do you even have to ask me … you could've googled it\"\n\n"
        "    NOISE bodies:\n%s\n\n"
        "    REPEATED bodies (the same sentence sent more than once):\n%s\n\n"
        "WHAT TO DO\n"
        "  1. Read the gate in `bin/textsend.py` (workstream `ws-textout` built it; if it is absent,\n"
        "     that is the fault). Every outbound body addressed to an owner number must classify as\n"
        "     QUESTION (with the evidence we gathered), RESULT (a conclusion naming the thing and\n"
        "     the answer), or ALERT -- and nothing else leaves.\n"
        "  2. For each NOISE body above, find its composer: an acknowledgement comes from\n"
        "     `ack_filed_text()`, an internal instruction is an owner-queue row body sent verbatim,\n"
        "     a probe string is a test that reached the transport. Fix the COMPOSER, not the string.\n"
        "  3. Re-run the gate's replay harness over the last 48 h and paste the verdicts. The noise\n"
        "     bodies above must be refused; the real questions and results must pass.\n"
        "  4. Prove it with `python3 ~/bin/text-health.py` (0 FAIL) and this source: it must print\n"
        "     `quiet` when you are done, and it is the instrument that keeps it that way.\n\n"
        "DO NOT send anything to anyone while you do this, and do not edit the durable record to\n"
        "make the count look better: the point is the next message he gets, not this number.") % (
        datetime.now(timezone.utc).isoformat(timespec="seconds"), window_note, path,
        len(delivered), counts["QUESTION"], counts["RESULT"], counts["ALERT"], counts["NOISE"],
        undelivered,
        examples, repeat_lines)

    return [Finding(
        subject="owner-question-noise:%s" % day,
        prompt=prompt,
        priority="normal",
        kind="repair",
        context=str({"window_hours": WINDOW_HOURS, "outbound": len(rows),
                     "delivered": len(delivered), "undelivered": undelivered, "counts": counts,
                     "noise": len(noise), "repeats": len(repeats), "store": str(path)}),
        cooldown_seconds=COOLDOWN_SECONDS,
    )]


def _selftest() -> int:
    """Assert the classifier against the EXACT bodies the owner actually received.

    An instrument nobody runs is decoration, and a classifier that drifts quietly is worse:
    it would report a clean channel while the noise went on. These are the real strings from
    `~/.sms-inbox/inbox.db` on 2026-10-02, so a regression names the message it broke on.
    """
    cases = [
        # (body, expected) -- the seven shapes that must never leave again
        ("Got it - filed as housekeeping#392.", "NOISE"),
        ("Got it - filed as housekeeping#390.", "NOISE"),
        ("Got it - I have it and I am on it.", "NOISE"),
        ("Remembered.", "NOISE"),
        ("Captured as a task.", "NOISE"),
        ("This is the turn-ledger probe; if you see this, the gate failed.", "NOISE"),
        ("Let me pull up the details on that Topgolf charge for you.", "NOISE"),
        ("[q1790960402] Amazon order history in the ledger is stale (newest order 2026-09-10). "
         "On the desktop (ZABZ-YOGA) run scripts/finance/account-scrapers/login_amazon.py", "NOISE"),
        ("Selftest passed. I ran the one command you asked for and wrote "
         "/tmp/owner-text-release-selftest.txt", "NOISE"),
        # ... and the three shapes the channel exists for
        ("CFO [ask-1790962130]: 320.00 at Data Reclos on 30 Sep, card ending 2005. "
         "Statement says: DATA RECLos Angeles. Also this merchant: 100.00 on 25 Sep. "
         "No guess from me - say what it was and I'll file it for good.", "QUESTION"),
        ("Pulled it from the card feed. The $173.55 Amazon charge is on your personal Chase card "
         "ending 9650 - the feed labels it E. ZABROWSKY, posted Sep 20.", "RESULT"),
        ("🚨 Reminder: CALL TOPGOLF EDISON GUEST CARE, (732) 374-4097 - reservation #9A0FE778, "
         "cancelled 9:27:42 PM ET", "ALERT"),
        ("☀️ Morning briefing — 2026-09-23\n\nCALENDAR: no upcoming events", "RESULT"),
    ]
    bad = 0
    for body, want in cases:
        got = classify(body)
        ok = got == want
        bad += 0 if ok else 1
        print("%-5s want=%-8s got=%-8s  %s" % ("ok" if ok else "FAIL", want, got,
                                              body.replace("\n", " / ")[:74]))
    print("RESULT: %d case(s), %d FAIL" % (len(cases), bad))
    return 1 if bad else 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    sys.exit(_flag.run(SOURCE, collect))
