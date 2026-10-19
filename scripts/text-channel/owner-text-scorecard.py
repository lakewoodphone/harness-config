#!/usr/bin/env python3
"""owner-text-scorecard.py — did the text deserve to exist?

WHY THIS EXISTS
---------------
`owner-text-audit.py` measures the CHANNEL: refusals, repeats, truncations, latency. Every
one of those is a property of a message in isolation. None of them can answer the owner's
actual complaint -- "so many of them I don't need text it to me" -- because that is a
question about CONSEQUENCE, not about wording.

The only evidence that a text to him was worth sending is what he DID next. So this tool
joins each delivered text to his next inbound message and judges the pair:

    ANSWERED    he replied within the window, and the reply is not a complaint
    COMPLAINED  he replied, and the reply is a complaint ("why did you", "stop sending",
                "I told you", "stupid", ...). The text cost him attention AND annoyed him.
    IGNORED     he said nothing at all for the whole window. Nobody can prove such a text
                was unwanted, but a text nobody answers is not doing work.

That is the number the overhaul has to move, and it is the number the woken audit session
must be told to move. `--flag` files ONE wake flag when IGNORED+COMPLAINED breaches a
threshold, with the worst template family named in the prompt, so the session that gets
woken has a target instead of a document.

MEASUREMENT DISCIPLINE (this estate's rule, 2026-10-14)
-------------------------------------------------------
* `sms_log` logs one send TWICE with the same `twilio_sid`. Every count here is over
  DISTINCT sids, and the report prints the rows-vs-sids arithmetic so the dedupe is visible.
* A row with an EMPTY sid was never carried by a provider. Those are counted separately and
  are never called delivered.
* "No reply" and "a reply that never came back" are different sentences and are printed
  separately: IGNORED requires that we can SEE the thread afterwards (his next inbound
  exists somewhere in the store), otherwise the outcome is UNMEASURABLE -- a window that
  ends before the store's newest inbound cannot be judged, and pretending otherwise would
  manufacture a low score for the most recent hours.

READ-ONLY, ALWAYS. `mode=ro` on every store.

EXIT CODES
    0   ran; every metric computed
    2   ran, but a store was unreachable -- the metric that needed it is null with a reason
    3   usage error

RUN
    python3 owner-text-scorecard.py                    # 14 days, human report
    python3 owner-text-scorecard.py --json --days 7
    python3 owner-text-scorecard.py --flag             # file ONE flag if a threshold breaks
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone

AUTHORITY_DB = os.environ.get("OWNER_TEXT_AUTHORITY_DB", "/root/authority.db")
RELAY_DB = os.environ.get("OWNER_TEXT_RELAY_DB", "/root/.owner-text/relay.db")
OWNER = os.environ.get("OWNER_PHONE_NUMBER", "+18483897895")
WAKE = os.environ.get("OWNER_TEXT_WAKE", "/root/bin/wake.py")

#: How long he has to respond before a text counts as ignored. Six hours: his median answer
#: latency is 152.8 min (owner-text-audit, 30 days), so 6h is ~2.4x the median and anything
#: past it was not waiting on him -- it was finished with.
DEFAULT_REPLY_WINDOW_H = 6.0

#: A reply that is itself a complaint is the strongest evidence a text should not have been
#: sent. The list is deliberately concrete: these are the phrases he actually used in the
#: 354 inbound messages on record.
COMPLAINT_RE = re.compile(
    r"(why (did|are|do) you|stop (sending|texting|asking)|i told you|already told you|"
    r"i said to stop|don'?t text me|don'?t ask me|you keep|again and again|"
    r"i don'?t need|pointless|useless|nonsense|stupid|dumb|annoying|literally just|"
    r"you literally|why would you|that'?s not what i|you'?re not listening)", re.I)

#: Refusals the channel made. Read from the relay's own verdict log and from the app's
#: suppressed rows, so the scorecard can show what the gates SAVED him as well as what
#: reached him.
THRESHOLDS = {
    # IGNORED + COMPLAINED as a share of judged texts. Above half and the channel is
    # mostly talking to itself.
    "dead_text_rate": 0.5,
}


def _now():
    return datetime.now(timezone.utc)


def _parse(value):
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def ro(path):
    if not os.path.exists(path):
        return None
    try:
        conn = sqlite3.connect("file:%s?mode=ro" % path, uri=True, timeout=5.0)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error:
        return None


def digits(value):
    return re.sub(r"\D", "", str(value or ""))


def family_of(body: str) -> str:
    """A coarse template family, so 'the finance engine' can be named rather than a text.

    First four significant words, which is what distinguishes "Reminder: Pay Yisroel
    Weinberg" from "Reminder: Chase CC payment" without a model.
    """
    words = [w for w in re.findall(r"[a-z0-9']+", (body or "").lower())
             if len(w) > 2 and w not in {"the", "and", "for", "you", "your", "this", "that",
                                         "with", "from", "have", "was", "are", "not", "but"}]
    return " ".join(words[:4]) or "(empty)"


def load_sms(window_start):
    """Every owner-directed outbound and every inbound, as (rows, sids, reason-if-null)."""
    conn = ro(AUTHORITY_DB)
    if conn is None:
        return None, "authority.db unreadable"
    try:
        rows = [dict(r) for r in conn.execute(
            """SELECT id, twilio_sid, direction, from_number, to_number, status, agent_id,
                      created_at, body
                 FROM sms_log
                WHERE (replace(replace(COALESCE(to_number,''),'+',''),'-','') LIKE ?
                    OR replace(replace(COALESCE(from_number,''),'+',''),'-','') LIKE ?)
                ORDER BY created_at ASC""",
            ("%" + digits(OWNER), "%" + digits(OWNER)),
        )]
        return rows, None
    except sqlite3.Error as exc:
        return None, str(exc)
    finally:
        conn.close()


def judge(rows, since, until, reply_window_h):
    """Join each delivered text to his next inbound. Returns the judgement list."""
    inbound = [r for r in rows if r["direction"] == "inbound"]
    outbound = [r for r in rows if r["direction"] == "outbound"]

    # Newest inbound in the store bounds what can be judged at all.
    newest_inbound = max((_parse(r["created_at"]) for r in inbound), default=None)

    seen_sids = set()
    judged = []
    rows_seen = 0
    for r in outbound:
        when = _parse(r["created_at"])
        if when is None or not (since <= when <= until):
            continue
        status = str(r.get("status") or "")
        if status in ("suppressed", "failed", "undelivered", "queued", "pending"):
            continue                      # never reached him; not this tool's question
        sid = str(r.get("twilio_sid") or "").strip()
        rows_seen += 1
        if sid:
            if sid in seen_sids:
                continue
            seen_sids.add(sid)
        elif not sid:
            # No sid means no provider accepted it. Count it, never call it delivered.
            pass

        deadline = when + timedelta(hours=reply_window_h)
        reply = None
        for m in inbound:
            mt = _parse(m["created_at"])
            if mt is None:
                continue
            if mt > when and mt <= deadline:
                reply = m
                break

        if reply is not None:
            body = str(reply.get("body") or "")
            outcome = "COMPLAINED" if COMPLAINT_RE.search(body) else "ANSWERED"
            reply_body = body
        elif newest_inbound is not None and deadline > newest_inbound:
            outcome = "UNMEASURABLE"
            reply_body = ""
        else:
            outcome = "IGNORED"
            reply_body = ""

        judged.append({
            "id": r["id"], "at": when.isoformat(), "sid": sid, "status": status,
            "agent": r.get("agent_id") or "", "family": family_of(r["body"] or ""),
            "outcome": outcome, "body": (r["body"] or "")[:160],
            "reply": reply_body[:120],
        })

    return {"judged": judged, "rows_seen": rows_seen, "distinct_sids": len(seen_sids),
            "newest_inbound": newest_inbound.isoformat() if newest_inbound else None}



# ---------------------------------------------------------------------------------------
# THE CONFORMANCE CENSUS (added 2026-10-19).
#
# The dead-text rate answers "did this text do any work", and moves over weeks. It cannot say
# whether the GUARDS are holding: if the quiet-hours rule and the internal-prose rule are doing
# their job, nothing they would refuse should reach him at all - and if something does, that is
# a defect that shipped, not a slow trend.
#
# So count it directly: every text that reached him in the window, scored against the guards
# that are live NOW. A rising number means a bypass, a regression, or a guard switched off.
# ---------------------------------------------------------------------------------------
RELAY_DIR = os.environ.get("OWNER_TEXT_RELAY_DIR", "/root/bin")
_GUARD_FUNCS = ("internal_prose", "credential_request")


def _load_relay():
    """The live relay module, or None. Never raises - a census must not break the scorecard."""
    try:
        if RELAY_DIR not in sys.path:
            sys.path.insert(0, RELAY_DIR)
        import owner_text_relay  # noqa: WPS433 - deliberate late import from a sibling dir
        return owner_text_relay
    except Exception:
        return None


def conformance(rows, since):
    """{delivered, would_refuse, by_class, rate} over texts that reached him in the window."""
    relay = _load_relay()
    if relay is None:
        return {"available": False,
                "why": "owner_text_relay not importable from %s" % RELAY_DIR,
                "unmeasured": ["conformance"]}
    since_s = since.isoformat() if hasattr(since, "isoformat") else str(since)
    delivered = 0
    flagged = 0
    rewrites = 0
    by_class = {}
    examples = []
    seen_sids = set()
    for r in rows:
        if r.get("direction") != "outbound":
            continue
        if (r.get("status") or "").lower() not in ("delivered", "sent"):
            continue
        if str(r.get("created_at") or "") < since_s:
            continue
        # ONE TEXT IS ONE EVENT. `sms_log` records the same send twice - an audit row from
        # `_audited_send` and a second row from the caller - so counting rows would double
        # every figure here exactly as it did in the audit.
        sid = r.get("twilio_sid")
        key = sid if sid and sid not in ("twiml-reply",) else ("id", r.get("id"))
        if key in seen_sids:
            continue
        seen_sids.add(key)
        delivered += 1
        body = r.get("body") or ""
        # THROUGH THE GATE. `submit()` first offers a reminder-class body to `_rescue_reminder()`,
        # which rewrites an instruction-shaped reminder into a sentence and sends the readable
        # remainder. Asking the guards about the RAW body charges the channel for messages the
        # gate would have rewritten and delivered - measured 2026-10-19: 9 of 34 reminder texts,
        # every one of them a real reminder (Weinberg settlement, Fisher SD card, Weitman bench).
        # The rescued text is what the guards actually see, so it is what this census must score.
        rescued = body
        rescue_note = ""
        fn_rescue = getattr(relay, "_rescue_reminder", None)
        if callable(fn_rescue):
            try:
                got_r = fn_rescue(body, OWNER, r.get("subsystem") or "cron")
                if isinstance(got_r, tuple) and len(got_r) == 2:
                    rescued, rescue_note = got_r[0], str(got_r[1] or "")
            except Exception:
                rescued, rescue_note = body, ""
        if rescued != body:
            rewrites += 1
        hits = []
        for name in _GUARD_FUNCS:
            fn = getattr(relay, name, None)
            if not callable(fn):
                continue
            try:
                got = fn(rescued)
            except Exception:
                got = None
            if got:
                hits.append(name)
        if hits:
            flagged += 1
            for name in hits:
                by_class[name] = by_class.get(name, 0) + 1
            if len(examples) < 5:
                examples.append({"at": r.get("created_at"), "classes": hits,
                                 "body": " ".join(body.split())[:120]})
    return {"available": True, "delivered": delivered, "would_refuse": flagged,
            "rewritten": rewrites, "by_class": by_class, "examples": examples,
            "rate": (flagged / delivered) if delivered else None}

def summarise(result):
    judged = result["judged"]
    counts = {"ANSWERED": 0, "COMPLAINED": 0, "IGNORED": 0, "UNMEASURABLE": 0}
    by_family = {}
    for j in judged:
        counts[j["outcome"]] = counts.get(j["outcome"], 0) + 1
        fam = by_family.setdefault(j["family"], {"ANSWERED": 0, "COMPLAINED": 0,
                                                 "IGNORED": 0, "UNMEASURABLE": 0,
                                                 "n": 0, "examples": []})
        fam[j["outcome"]] = fam.get(j["outcome"], 0) + 1
        fam["n"] += 1
        if len(fam["examples"]) < 2 and j["outcome"] in ("IGNORED", "COMPLAINED"):
            fam["examples"].append(j["body"][:90])

    measurable = counts["ANSWERED"] + counts["COMPLAINED"] + counts["IGNORED"]
    dead = counts["COMPLAINED"] + counts["IGNORED"]
    rate = (dead / measurable) if measurable else None

    worst = sorted(
        ({"family": k, "n": v["n"], "dead": v["COMPLAINED"] + v["IGNORED"],
          "examples": v["examples"]}
         for k, v in by_family.items() if v["n"] >= 2),
        key=lambda d: (-d["dead"], -d["n"]))[:8]

    return {"counts": counts, "measurable": measurable, "dead_text_rate": rate,
            "worst_families": worst, "families": len(by_family)}


def report(result, summary, days, window_h):
    conf = result.get("conformance") or {}
    c = summary["counts"]
    print("=== owner text scorecard — last %g day(s), reply window %gh ===" % (days, window_h))
    print("rows counted            %d  (a send is logged twice; DISTINCT sids = %d)"
          % (result["rows_seen"], result["distinct_sids"]))
    print("newest inbound on file  %s" % result["newest_inbound"])
    print()
    print("  ANSWERED      %4d" % c["ANSWERED"])
    print("  COMPLAINED    %4d   <- the text cost him attention AND annoyed him" % c["COMPLAINED"])
    print("  IGNORED       %4d   <- nobody answered; the text did no work" % c["IGNORED"])
    print("  UNMEASURABLE  %4d   <- window ends after his last inbound; not counted" % c["UNMEASURABLE"])
    print()
    if summary["dead_text_rate"] is None:
        print("dead-text rate          not measurable (no judged texts)")
    else:
        print("dead-text rate          %.1f%% of %d judged (COMPLAINED+IGNORED)"
              % (100 * summary["dead_text_rate"], summary["measurable"]))
    print()
    print("=== worst families (>= 2 texts) ===")
    if not summary["worst_families"]:
        print("  none")
    for fam in summary["worst_families"]:
        print("  %-42s %d dead of %d" % (fam["family"][:42], fam["dead"], fam["n"]))
        for ex in fam["examples"][:1]:
            print("        e.g. %s" % ex)


def file_flag(summary, days):
    rate = summary["dead_text_rate"]
    if rate is None or rate <= THRESHOLDS["dead_text_rate"]:
        print("no flag: dead-text rate %s within threshold %s"
              % ("null" if rate is None else "%.2f" % rate, THRESHOLDS["dead_text_rate"]))
        return 0
    worst = summary["worst_families"][0] if summary["worst_families"] else None
    # WEEKLY, not daily: the underlying rate moves over days, and a daily subject would
    # file a fresh flag every morning while the condition is unchanged. One session per
    # ISO week is enough to move one bounded thing, and the flag names which one.
    _y, _w, _ = _now().isocalendar()
    subject = "owner-text:scorecard:%04d-W%02d" % (_y, _w)
    prompt = (
        "The owner text channel's scorecard breached its threshold: %.0f%% of %d judged "
        "texts in the last %g days were ignored or complained about (threshold %.0f%%).\n\n"
        "Worst family: %s (%d dead of %d). Examples: %s\n\n"
        "DO ONE BOUNDED THING: find why that family's texts are not worth answering and "
        "land one change with a before/after count. Do not re-audit the whole channel; "
        "`owner-text-audit.py --days %d` and `owner-text-scorecard.py --days %d` are already "
        "the instruments. Record the change in the journal and in "
        "scripts/text-channel/README.md."
        % (100 * rate, summary["measurable"], days, 100 * THRESHOLDS["dead_text_rate"],
           worst["family"] if worst else "(none)", worst["dead"] if worst else 0,
           worst["n"] if worst else 0,
           (worst["examples"][0] if worst and worst["examples"] else "(none)"),
           int(days), int(days))
    )
    cmd = [sys.executable, WAKE, "flag", "--subject", subject, "--prompt", prompt,
           "--kind", "owner-text", "--source", "owner-text-scorecard", "--priority", "normal"]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        print("flag %s -> %s" % (subject, (out.stdout or out.stderr or "").strip()[:300]))
        return 0
    except Exception as exc:  # noqa: BLE001
        print("flag filing FAILED: %r" % (exc,), file=sys.stderr)
        return 2



#: The census threshold. 10% of the texts that reach him being ones the guards would refuse is a
#: regression, not noise; the first corrected reading was 11 of 77 (14%), and every one of those
#: eleven was a real defect of the composer that produced it.
CONFORMANCE_THRESHOLD = float(os.environ.get("OWNER_TEXT_CONFORMANCE_THRESHOLD", "0.10"))


def file_conformance_flag(conf, days):
    """File ONE wake when too many delivered texts are ones the guards would refuse.

    Independent of the dead-text flag: that one watches whether his texts do any work, this one
    watches whether the guards are holding. A guard regression moves this number and not that one.
    """
    if not conf or not conf.get("available"):
        print("no conformance flag: %s" % (conf or {}).get("why", "not measured"))
        return 0
    delivered = int(conf.get("delivered") or 0)
    refused = int(conf.get("would_refuse") or 0)
    if delivered < 20:
        print("no conformance flag: only %d delivered texts, too few to judge" % delivered)
        return 0
    rate = refused / delivered
    if rate <= CONFORMANCE_THRESHOLD:
        print("no conformance flag: %d of %d refused (%.1f%%) within threshold %.0f%%"
              % (refused, delivered, 100 * rate, 100 * CONFORMANCE_THRESHOLD))
        return 0
    y, w, _ = _now().isocalendar()
    subject = "owner-text:conformance:%04d-W%02d" % (y, w)
    classes = ", ".join("%s=%d" % (k, v)
                        for k, v in sorted((conf.get("by_class") or {}).items(),
                                           key=lambda kv: -kv[1])) or "(none named)"
    examples = "; ".join("%s :: %s" % (e.get("at", "")[:16], e.get("body", "")[:80])
                         for e in (conf.get("examples") or [])[:3]) or "(none)"
    prompt = (
        "%d of the %d texts that reached him in the last %g days are ones the live guards would "
        "refuse (%.1f%%, threshold %.0f%%). Classes: %s. Examples: %s\n\n"
        "DO ONE BOUNDED THING. The gate already refuses these - which means the defect is in the "
        "COMPOSER that writes them, and the repair belongs at the sender. Find the code that "
        "emits this class, make it write ONE human sentence (no paths, no task ids, no "
        "instruction verbs), and prove it by re-running `owner-text-scorecard.py` and reading the "
        "conformance block.\n\n"
        "Do NOT strengthen the guard to hide it: suppressing harder turns a bad message into no "
        "message, and for a reminder class that deletes the reminder. %s were rewritten by the "
        "gate in this window - those are delivered, not lost, and are not counted here."
        % (refused, delivered, days, 100 * rate, 100 * CONFORMANCE_THRESHOLD, classes, examples,
           conf.get("rewritten") or 0)
    )
    cmd = [sys.executable, WAKE, "flag", "--subject", subject, "--prompt", prompt,
           "--kind", "owner-text", "--source", "owner-text-conformance", "--priority", "normal"]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        print("flag %s -> %s" % (subject, (out.stdout or out.stderr or "").strip()[:300]))
        return 0
    except Exception as exc:                                       # noqa: BLE001
        print("conformance flag filing FAILED: %r" % (exc,), file=sys.stderr)
        return 2


def main(argv=None):
    ap = argparse.ArgumentParser(description="did the owner text deserve to exist?")
    ap.add_argument("--days", type=float, default=14.0)
    ap.add_argument("--reply-window", type=float, default=DEFAULT_REPLY_WINDOW_H)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--flag", action="store_true")
    args = ap.parse_args(argv)

    if args.days <= 0 or args.reply_window <= 0:
        print("bad --days/--reply-window", file=sys.stderr)
        return 3

    until = _now()
    since = until - timedelta(days=args.days)
    rows, why = load_sms(since)
    if rows is None:
        out = {"ok": False, "reason": why, "unmeasured": ["everything"]}
        print(json.dumps(out, indent=2) if args.json else "cannot read %s: %s" % (AUTHORITY_DB, why))
        return 2

    result = judge(rows, since, until, args.reply_window)
    result["conformance"] = conformance(rows, since)
    summary = summarise(result)

    if args.json:
        print(json.dumps({"ok": True, "window": {"since": since.isoformat(),
                                                 "until": until.isoformat()},
                          "result": {k: v for k, v in result.items() if k != "judged"},
                          "summary": summary, "judged": result["judged"]}, indent=2))
    else:
        report(result, summary, args.days, args.reply_window)
        conf = result.get("conformance") or {}
        print()
        print("  CONFORMANCE - texts that reached him and the live guards would refuse")
        if not conf.get("available"):
            print("    NOT MEASURED: %s" % conf.get("why"))
        else:
            rate = conf.get("rate")
            print("    %d of %d delivered texts   (%s) refused by the guards"
                  % (conf.get("would_refuse", 0), conf.get("delivered", 0),
                     "%.1f%%" % (rate * 100) if rate is not None else "n/a"))
            if conf.get("rewritten"):
                print("    %d more were REMINDERS the gate rewrites and sends - not refused, "
                      "not lost" % conf["rewritten"])
            for k, v in sorted((conf.get("by_class") or {}).items(), key=lambda kv: -kv[1]):
                print("      %-20s %d" % (k, v))
            for e in (conf.get("examples") or [])[:3]:
                print("      e.g. %s %s | %s"
                      % (str(e.get("at"))[:16], e.get("classes"), e.get("body")))

    if args.flag:
        # BOTH CONDITIONS, both filed, neither able to suppress the other.
        rc1 = file_flag(summary, args.days)
        rc2 = file_conformance_flag(result.get("conformance") or {}, args.days)
        return rc1 or rc2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
