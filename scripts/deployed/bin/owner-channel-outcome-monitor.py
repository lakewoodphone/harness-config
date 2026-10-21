#!/usr/bin/env python3
"""owner-channel-outcome-monitor.py — measure whether the owner's channel DELIVERED.

WHY THIS EXISTS (2026-10-20)
----------------------------
`/root/bin/text-health.py` reported 20 checks / 0 FAIL while the owner received no
finance text for two days and 13 real messages sat refused in the queue. Every one of
its checks measures WIRING: the model catalogue resolves, the ceiling is single-sourced,
the flood brake is deployed, a `sent` row has an `sms_log` row behind it. None of them
measures the only two things a human cares about:

  1. ARRIVAL  — did anything reach his phone in a window that should have carried one?
  2. LEGITIMACY — was each refusal one a human would agree with, or an artefact?

A refusal is legitimate when it says something true about the message ("duplicate of one
already sent", "engine noise", "past its shelf life"). It is illegitimate when it says
something true only about our configuration ("urgency is below the threshold"), because
that refusal has no relationship to whether the owner needed the message — and it is
exactly the refusal that can hold forever.

WHAT IT PRINTS
--------------
One line per check, `OK` / FAIL `code`. Exit 0 always (it is a report, not a gate), and
exit 2 is never used, so a cron caller cannot mistake a finding for a crash.

READ-ONLY. It opens every store `mode=ro` and writes nothing, anywhere.

USAGE
    owner-channel-outcome-monitor.py            # human report
    owner-channel-outcome-monitor.py --json     # machine
    owner-channel-outcome-monitor.py --hours 48 # quiet window to judge against
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HOME = Path.home()
AUTH_DB = Path(os.environ.get("AUTHORITY_DB", HOME / "authority.db"))
CFO_ASK_DB = Path(os.environ.get("CFO_ASK_DB", HOME / ".cfo-asks" / "asks.db"))

#: A refusal that names only our own configuration, never the message. These are the
#: strings that can hold a row forever; see `owner_notifications.owner_sms_allowed`.
CONFIG_REFUSAL_MARKERS = (
    "below the send threshold",
)

#: A message older than this, still in a non-terminal state, is a limbo row. The
#: lifecycle sweep's own longest horizon is 336h (urgent_email), so nothing legitimate
#: should exceed it; 48h is used for the "should have moved" judgement because a
#: reminder's own horizon is 24h.
LIMBO_HOURS = 48

#: Nothing reached him for this long while the queue was non-empty = a blackout. The
#: owner's own stated tolerance is "about one question a day"; two days of no text at
#: all, with real work waiting, is the failure this file exists to surface.
SILENCE_HOURS = 36


def _ro(path: Path) -> sqlite3.Connection | None:
    if not path.exists():
        return None
    try:
        return sqlite3.connect("file:%s?mode=ro" % path, uri=True, timeout=5)
    except sqlite3.Error:
        return None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _age_hours(stamp: str | None) -> float | None:
    if not stamp:
        return None
    try:
        t = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return (_now() - t).total_seconds() / 3600.0


def _load_events(conn: sqlite3.Connection) -> dict:
    """Everything the queue can tell us about arrival and refusal."""
    out: dict = {
        "sent": [],        # (id, sent_at, urgency, reason)
        "open": [],        # dicts: id, urgency, status, created_at, attempts, error, reason
        "refused_config": 0,
        "refused_other": 0,
        "refusals": {},
    }
    try:
        rows = conn.execute(
            "SELECT id, sent_at, urgency, COALESCE(reason,'') FROM owner_message_queue "
            "WHERE status='sent' AND sent_at IS NOT NULL "
            "ORDER BY sent_at DESC LIMIT 200"
        ).fetchall()
        out["sent"] = rows
    except sqlite3.Error as exc:
        out["error_sent"] = str(exc)

    try:
        rows = conn.execute(
            "SELECT id, COALESCE(urgency,'normal'), status, created_at, "
            "COALESCE(send_attempts,0), COALESCE(last_send_error,''), "
            "COALESCE(reason,'') "
            "FROM owner_message_queue WHERE status IN ('held','queued') "
            "ORDER BY created_at"
        ).fetchall()
        for r in rows:
            out["open"].append({
                "id": r[0], "urgency": r[1], "status": r[2], "created_at": r[3],
                "attempts": r[4], "error": r[5], "reason": r[6],
                "age_h": _age_hours(r[3]),
            })
            err = (r[5] or "").lower()
            key = err.split("(")[-1].split(")")[0].strip() if "(" in err else err[:80]
            out["refusals"][key or "(none)"] = out["refusals"].get(key or "(none)", 0) + 1
    except sqlite3.Error as exc:
        out["error_open"] = str(exc)
    return out


def _cfo_state() -> dict:
    conn = _ro(CFO_ASK_DB)
    if conn is None:
        return {"ok": False, "error": "asks.db missing"}
    # `sent=1` IS NOT PROOF OF DELIVERY, and trusting it hid three dead questions.
    # Measured 2026-10-21: asks 42/44/45 carry sent=1 and a provider sid, but the three
    # were composed 2026-10-15 and had no answer five days later; the row records that
    # we ASKED the provider, never that a phone lit up. What matters to a human is the
    # unanswered AGE, so that is what this measures -- not whether the flag is set.
    try:
        asked = conn.execute(
            "SELECT asked_at FROM ask WHERE sent=1 ORDER BY id DESC LIMIT 1"
        ).fetchone()
        unanswered = conn.execute(
            "SELECT count(*) FROM ask WHERE sent=1 AND answered_at IS NULL"
        ).fetchone()[0]
        stale = conn.execute(
            "SELECT count(*) FROM ask WHERE sent=1 AND answered_at IS NULL "
            "AND julianday('now') - julianday(asked_at) > 72"
        ).fetchone()[0]
        today = conn.execute(
            "SELECT count(*) FROM ask WHERE sent=1 AND date(asked_at)=date('now')"
        ).fetchone()[0]
        # The oldest question that is still open, whatever its `sent` flag says -- an
        # ask composed and never answered is a question the owner may never have seen.
        # ONLY A QUESTION THAT WAS ACTUALLY SENT is a question he did not
        # answer.  Measured 2026-10-21: 56 rows in this store were composed and
        # never sent (parked drafts, older bodies); counting them made L5 read
        # "189 h unanswered" when the owner had been asked nothing at all.
        oldest_open = conn.execute(
            "SELECT asked_at FROM ask WHERE sent=1 AND answered_at IS NULL "
            "ORDER BY asked_at ASC LIMIT 1"
        ).fetchone()
        return {
            "ok": True,
            "last_sent_at": asked[0] if asked else None,
            "last_age_h": _age_hours(asked[0]) if asked else None,
            "unanswered": unanswered,
            "stale_unanswered": stale,
            "sent_today": today,
            "oldest_open_at": oldest_open[0] if oldest_open else None,
            "oldest_open_age_h": _age_hours(oldest_open[0]) if oldest_open else None,
        }
    finally:
        conn.close()


def _shift_freshness() -> dict:
    """The CFO engine's own log: a gap here is the engine not running."""
    path = HOME / ".cfo" / "shifts.jsonl"
    if not path.exists():
        return {"ok": False, "error": "shifts.jsonl missing"}
    newest_ts = None
    try:
        with path.open("rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - 65536))
            tail = fh.read().decode("utf-8", "replace")
        for line in reversed(tail.splitlines()):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            newest_ts = rec.get("at") or rec.get("started")
            if newest_ts:
                break
    except OSError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "last_shift_at": newest_ts, "last_shift_age_h": _age_hours(newest_ts)}


def _delivery_wired() -> dict:
    """Is the ONLY program that turns a queue row into a text actually scheduled?

    Measured 2026-10-21: the CFO engine files owner questions into
    `owner_decision_queue` (`cfo-shift.py:1240`), and `owner_ask.py` is the only
    program that reads that table and texts a row (`owner-ask.py:39,374`). It was in
    no crontab, no systemd unit and had never run: four questions sat `pending` with
    nothing to send them. A producer with no deliverer is silent by construction, and
    no liveness check can see it because every component is healthy on its own.
    """
    out = {"ok": True, "detail": "", "pending": 0, "oldest_age_h": None}
    conn = _ro(AUTH_DB)
    if conn is None:
        out.update(ok=False, detail="authority.db unreadable")
        return out
    try:
        row = conn.execute(
            "SELECT count(*), min(asked_at) FROM owner_decision_queue "
            "WHERE status='pending'"
        ).fetchone()
        out["pending"] = int(row[0] or 0)
        out["oldest_age_h"] = _age_hours(row[1]) if row[1] else None
    except sqlite3.Error as exc:
        out.update(ok=False, detail="owner_decision_queue unreadable: %s" % exc)
        return out
    finally:
        conn.close()

    # Scheduled? A crontab line OR a systemd unit both count; absence from both is the
    # failure. We look at the running host's crontab and unit list, read-only.
    import subprocess
    scheduled = False
    where = []
    try:
        cron = subprocess.run(["crontab", "-l"], capture_output=True, text=True,
                              timeout=5).stdout
        if "owner-ask" in cron:
            scheduled = True
            where.append("crontab")
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        units = subprocess.run(["systemctl", "list-units", "--all", "--no-legend",
                                "--no-pager"], capture_output=True, text=True,
                               timeout=5).stdout
        if "owner-ask" in units:
            scheduled = True
            where.append("systemd")
    except (OSError, subprocess.SubprocessError):
        pass

    out["scheduled"] = scheduled
    out["where"] = where
    if out["pending"] and not scheduled:
        out.update(ok=False, detail=(
            "%d owner question(s) pending in owner_decision_queue, oldest %.0f h, and "
            "the only program that can text them (owner-ask.py) is in no crontab and no "
            "systemd unit -- a producer with no deliverer"
            % (out["pending"], out["oldest_age_h"] or 0)))
    elif out["pending"]:
        out.update(detail="%d pending, deliverer scheduled (%s)"
                          % (out["pending"], ",".join(where)))
    else:
        out.update(detail="no pending owner questions")
    return out


def evaluate(hours: int = SILENCE_HOURS) -> dict:
    results: list[dict] = []

    def add(code: str, ok: bool, detail: str) -> None:
        results.append({"check": code, "ok": bool(ok), "detail": detail})

    conn = _ro(AUTH_DB)
    if conn is None:
        add("A0", False, "authority.db is unreadable at %s" % AUTH_DB)
        return {"ok": False, "results": results}
    try:
        ev = _load_events(conn)
    finally:
        conn.close()

    # ---- L1 ARRIVAL: did anything reach him inside the window --------------------
    last_age = None
    if ev["sent"]:
        last_age = _age_hours(ev["sent"][0][1])
    open_n = len(ev["open"])
    if last_age is None:
        add("L1", False, "NO owner message has ever been recorded as sent")
    elif last_age > hours:
        add("L1", False,
            "nothing sent to the owner for %.1f h (limit %d h); %d message(s) waiting"
            % (last_age, hours, open_n))
    else:
        add("L1", True,
            "newest send to the owner %.1f h ago; %d message(s) waiting"
            % (last_age, open_n))

    # ---- L2 LEGITIMACY: is any refusal purely about our configuration? ----------
    config_refused = [r for r in ev["open"]
                      if any(m in (r["error"] or "").lower() for m in CONFIG_REFUSAL_MARKERS)]
    if config_refused:
        worst = max(config_refused, key=lambda r: r["attempts"])
        add("L2", False,
            "%d message(s) refused ONLY by a configuration threshold, not by anything "
            "about the message; worst #%d refused %d time(s) over %.0f h (%s)"
            % (len(config_refused), worst["id"], worst["attempts"],
               worst["age_h"] or 0, worst["error"][:90]))
    else:
        add("L2", True, "every waiting message is refused for a reason about itself")

    # ---- L3 LIMBO: nothing may sit past its own horizon ------------------------
    limbo = [r for r in ev["open"] if (r["age_h"] or 0) > LIMBO_HOURS]
    if limbo:
        oldest = max(limbo, key=lambda r: r["age_h"] or 0)
        add("L3", False,
            "%d message(s) waiting longer than %d h; oldest #%d at %.0f h, status %s"
            % (len(limbo), LIMBO_HOURS, oldest["id"], oldest["age_h"], oldest["status"]))
    else:
        add("L3", True, "no message waits past %d h" % LIMBO_HOURS)

    # ---- L4 RETRY CHURN: a row retried many times is a row nobody decided ------
    churn = [r for r in ev["open"] if r["attempts"] >= 8]
    if churn:
        worst = max(churn, key=lambda r: r["attempts"])
        add("L4", False,
            "%d row(s) attempted 8+ times without a terminal state; worst #%d at %d "
            "attempts" % (len(churn), worst["id"], worst["attempts"]))
    else:
        add("L4", True, "no row is being retried into a refusal loop")

    # ---- L5 THE CFO'S MOUTH ---------------------------------------------------
    cfo = _cfo_state()
    if not cfo.get("ok"):
        add("L5", False, "CFO ask store unavailable: %s" % cfo.get("error"))
    else:
        # Not "no question today" -- the queue can legitimately be empty. The two real
        # failures are an old question nobody answered, and a channel that never carries
        # one. Age is judged on EVERY open ask, not only the ones flagged sent: the flag
        # records that we asked a provider, never that a phone lit up.
        open_age = cfo.get("oldest_open_age_h")
        if open_age is not None and open_age > 72:
            add("L5", False,
                "oldest CFO question is %.0f h old and still unanswered (asked %s); "
                "%d unanswered of %d flagged sent"
                % (open_age, str(cfo.get("oldest_open_at"))[:19],
                   cfo["unanswered"], cfo["stale_unanswered"] + cfo["unanswered"]))
        else:
            add("L5", True,
                "CFO: %d sent today, %d unanswered, oldest open %.0f h; newest ask %.1f h ago"
                % (cfo["sent_today"], cfo["unanswered"], open_age or 0,
                   cfo["last_age_h"] or 0))

    # ---- L6 THE ENGINE ---------------------------------------------------------
    shift = _shift_freshness()
    if not shift.get("ok"):
        add("L6", False, "CFO shift log unavailable: %s" % shift.get("error"))
    elif shift.get("last_shift_age_h") is not None and shift["last_shift_age_h"] > 6:
        add("L6", False,
            "the CFO shift engine has not run for %.1f h (last %s) while cron fires "
            "every 30 min" % (shift["last_shift_age_h"], shift["last_shift_at"]))
    else:
        add("L6", True,
            "CFO shift engine last ran %.1f h ago" % (shift["last_shift_age_h"] or 0))

    # ---- L7 DELIVERER: a producer with no deliverer is silent by construction ------
    wire = _delivery_wired()
    add("L7", wire.get("ok", False), wire.get("detail") or "delivery wiring not measured")

    failed = [r for r in results if not r["ok"]]
    return {
        "ok": not failed,
        "checked_at": _now().isoformat(),
        "results": results,
        "failed": [r["check"] for r in failed],
        "queue_open": open_n,
        "last_send_age_h": last_age,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--hours", type=int, default=SILENCE_HOURS)
    args = ap.parse_args(argv)
    report = evaluate(hours=max(1, int(args.hours)))
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=False))
        return 0
    print("OWNER-CHANNEL OUTCOME %s" % report["checked_at"][:19] + "Z")
    for r in report["results"]:
        print("%-5s %-3s %s" % ("OK" if r["ok"] else "FAIL", r["check"], r["detail"]))
    print("RESULT: %d check(s), %d FAIL%s"
          % (len(report["results"]), len(report["failed"]),
             (" - " + ",".join(report["failed"])) if report["failed"] else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
