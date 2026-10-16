#!/usr/bin/env python3
"""premise-check.py - re-measure an owner-queue row's PREMISE at delivery time.

WHY THIS EXISTS
===============
`owner-queue.py amend` already carries the rule this tool automates, in its own docstring:

    "an item is a statement about the world at FILING time. When the measurement moves, the
     item moves with it, or the next shift spends its opening minutes chasing a ghost."

`amend` is the MECHANISM; nothing ran it. Measured 2026-10-15, one session, over one queue of
127 rows that had been reduced to 24:

  * #448 asked the owner to approve 20-30 USD/month to resize the box to a 4 vCPU / 16 GB
    CCX23. The box ALREADY WAS one (nproc 4, MemTotal 15.2 GiB, SwapTotal 8 GiB, and
    docs/mesh/188 names it). Approving it would have paid twice for a machine in service.
  * #514 and #449 had both been RESOLVED BY REALITY before he read them (AI balance 261,
    Telnyx funded 10597 cents) - after they had already been handed to him.
  * #492's stated "75 days late" was 77 by the time he would read it, and grows by one a day.
  * #512 asked about "23 recording names" while its own amendment said 30 files and neither
    card was his.
  * #465's tax figure reproduced to the cent - which was only knowable by re-running it.

Every one of those is the same defect: the row was TRUE when filed and was PRESENTED later.
A queue row decays, and a row whose premise is a live number has a shelf life of hours.

WHAT IT DOES
============
A named PROBE re-measures one row's premise and returns a verdict:

    fresh     the premise still holds; the measurement is recorded, nothing else changes
    changed   the premise has MOVED; the row is amended with the fresh measurement, and the
              delivery gate refuses to present it until that has happened
    unprobed  no probe matches this row's shape - honest, and counted, never silently "fresh"
    unknown   a probe was matched but could not run (missing source, unreadable store)

Design rules, each for a reason learned here:
  * EVERY probe is READ-ONLY. Nothing in this file writes to any system other than the
    check table and `owner-queue.py amend`.
  * A probe failure is NEVER 'fresh'. It is `unknown`, because an empty or failed result is a
    refusal, not health.
  * A probe is only re-run when its recorded check is older than expected_max_age_hours, which
    is the shape `finance_source_registry` already uses for data sources. Re-running is
    idempotent: the same measurement produces the same row.
  * `sweep` defaults to --dry-run. Writing requires --apply, matching migrate-stale-flags.py.
  * Amendments go through `owner-queue.py amend` as a subprocess argument list, never a shell,
    so the queue's own P265 guard and no-shell rule still apply.

USAGE
=====
    premise-check.py probes                       # what probes exist and what they match
    premise-check.py check 465                    # one row, print the verdict, change nothing
    premise-check.py sweep --dry-run              # what is due, and what each would say
    premise-check.py sweep --apply                # re-measure, record, amend where changed
    premise-check.py gate 465                     # exit 0 if safe to present, 10 if it moved
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

DB = Path(os.environ.get("PREMISE_DB", "/root/authority.db"))
QUEUE = "/root/bin/owner-queue.py"
LEDGER = Path(os.environ.get("PREMISE_LEDGER", "/root/accounting-data/live/accounting.db"))

#: Default staleness budget for a probe that does not declare its own. Deliberately the same
#: ORDER OF MAGNITUDE as finance_source_registry's expected_max_age_days, but in hours,
#: because a decision premise moves faster than a data source: four of the five stale rows
#: measured on 2026-10-15 had moved within 48 hours of filing.
DEFAULT_MAX_AGE_HOURS = 6

VERDICTS = ("fresh", "changed", "unprobed", "unknown")


# --------------------------------------------------------------------------- #
# the check table
# --------------------------------------------------------------------------- #
def ensure_schema(con: sqlite3.Connection) -> None:
    con.execute(
        """CREATE TABLE IF NOT EXISTS owner_premise_check (
               row_id        INTEGER PRIMARY KEY,
               probe         TEXT NOT NULL,
               checked_at    TEXT NOT NULL,
               verdict       TEXT NOT NULL,
               detail        TEXT NOT NULL DEFAULT '',
               expect_max_h  INTEGER NOT NULL DEFAULT 6
           )"""
    )
    con.commit()


def record(con, row_id, probe, verdict, detail, expect_max_h):
    con.execute(
        "INSERT INTO owner_premise_check (row_id, probe, checked_at, verdict, detail, expect_max_h)"
        " VALUES (?,?,?,?,?,?)"
        " ON CONFLICT(row_id) DO UPDATE SET"
        "   probe=excluded.probe, checked_at=excluded.checked_at, verdict=excluded.verdict,"
        "   detail=excluded.detail, expect_max_h=excluded.expect_max_h",
        (row_id, probe, _now(), verdict, detail[:2000], int(expect_max_h)),
    )
    con.commit()


def last_check(con, row_id):
    return con.execute(
        "SELECT row_id, probe, checked_at, verdict, detail, expect_max_h"
        " FROM owner_premise_check WHERE row_id=?", (row_id,)).fetchone()


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def _parse(ts):
    if not ts:
        return None
    try:
        d = dt.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)


def hours_since(ts) -> float | None:
    d = _parse(ts)
    if d is None:
        return None
    return (dt.datetime.now(dt.timezone.utc) - d).total_seconds() / 3600.0


# --------------------------------------------------------------------------- #
# probes
#
# A probe takes (row_dict) and returns (verdict, detail, max_age_hours).
# It must never raise; a raised exception is caught by the caller and becomes 'unknown'.
# --------------------------------------------------------------------------- #
def _text(row) -> str:
    return " ".join(str(row.get(k) or "") for k in ("question", "context", "blocks",
                                                    "recommendation", "options_json"))


def _find_due(text):
    return [m.group(1) for m in re.finditer(r"due\s+(\d{4}-\d{2}-\d{2})", text)]


def probe_deadline(row):
    """A row with a stated due date. Recompute days remaining/overdue."""
    dues = _find_due(_text(row))
    if not dues:
        return None
    today = dt.date.today()
    parts = []
    for d in dues:
        try:
            when = dt.date.fromisoformat(d)
        except ValueError:
            continue
        delta = (when - today).days
        parts.append(f"{d}: {'in %d day(s)' % delta if delta >= 0 else '%d day(s) OVERDUE' % -delta}")
    if not parts:
        return None
    return ("fresh", "due dates as of today - " + "; ".join(parts), DEFAULT_MAX_AGE_HOURS)


def probe_elapsed(row):
    """A row that states an elapsed count ('N days late/old/overdue') against a due date.

    This is the #492 shape: correct when filed, +1 every day after. The row is not wrong on
    the day it is written and is wrong on every day it is read.
    """
    text = _text(row)
    dues = _find_due(text)
    m = re.search(r"(\d{1,4})\s+days?\s+(late|old|overdue|ago)", text, re.I)
    if not (dues and m):
        return None
    stated = int(m.group(1))
    try:
        due = dt.date.fromisoformat(dues[0])
    except ValueError:
        return None
    actual = (dt.date.today() - due).days
    detail = (f"stated {stated} days {m.group(2)}, measured {actual} days as of today "
              f"(due {dues[0]})")
    if actual != stated:
        return ("changed", detail + " - the row's figure has DRIFTED", 12)
    return ("fresh", detail, 12)


def probe_provider(row):
    """A row about an AI provider: is it actually being used, and failing?"""
    text = _text(row).lower()
    names = [n for n in ("deepinfra", "deep infra", "deepseek", "openrouter", "minimax",
                         "gemini", "openai", "anthropic", "qwen") if n in text]
    if not names:
        return None
    name = names[0]
    con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
    try:
        like = "%" + name.replace(" ", "") + "%"
        row2 = con.execute(
            "SELECT COUNT(*), SUM(CASE WHEN success=0 THEN 1 ELSE 0 END), MAX(created_at)"
            " FROM model_usage WHERE lower(provider) LIKE ? OR lower(model) LIKE ?",
            (like, like)).fetchone()
    except sqlite3.Error as exc:
        return ("unknown", "model_usage unreadable: %s" % exc, DEFAULT_MAX_AGE_HOURS)
    finally:
        con.close()
    n, fails, newest = row2 or (0, 0, None)
    if not n:
        return ("changed",
                f"NO '{name}' rows in model_usage at all - the provider is not in the routing, "
                f"so 'fix the card' is not repairing a live outage", DEFAULT_MAX_AGE_HOURS)
    return ("fresh", f"{name}: {n} calls, {fails or 0} failures, newest {newest}",
            DEFAULT_MAX_AGE_HOURS)


def probe_merchant(row):
    """A row about a RECURRING CHARGE: when did this merchant last post?

    NARROWED ON PURPOSE, after a real miss. The first version fired on any merchant name, so
    owner-queue row 465 - a sales-tax row that happens to mention Stripe in its own arithmetic -
    was measured as "stripe's newest ledger rows", which is true, irrelevant, and hides the
    deadline that is the row's actual premise. A probe that answers an adjacent question is a
    distraction wearing the costume of evidence. So a merchant probe now requires the row to be
    about the charge continuing - still billing, monthly, subscription, next debit, renewal -
    which is the shape of #207 (T-Mobile) and #463 (Audible).
    """
    text = _text(row).lower()
    if not any(k in text for k in ("still billing", "still live", "billing", "monthly",
                                   "subscription", "next debit", "renewal", "never cancelled",
                                   "still charging")):
        return None
    for needle in ("t-mobile", "tmobile", "audible", "us mobile", "usmobile", "telnyx",
                   "dialpad", "amazon prime", "verizon"):
        if needle in text:
            break
    else:
        return None
    if not LEDGER.exists():
        return ("unknown", "accounting ledger not found at %s" % LEDGER, DEFAULT_MAX_AGE_HOURS)
    con = sqlite3.connect("file:%s?mode=ro" % LEDGER, uri=True)
    try:
        rows = con.execute(
            "SELECT transaction_date, direction, ROUND(amount_cents/100.0,2), description"
            " FROM transactions WHERE lower(description) LIKE ?"
            " ORDER BY transaction_date DESC LIMIT 3", ("%" + needle + "%",)).fetchall()
    except sqlite3.Error as exc:
        return ("unknown", "ledger unreadable: %s" % exc, DEFAULT_MAX_AGE_HOURS)
    finally:
        con.close()
    if not rows:
        return ("changed",
                f"no '{needle}' charge has ever posted in the ledger - the row's premise that "
                f"it is still billing cannot be confirmed", DEFAULT_MAX_AGE_HOURS)
    newest = rows[0]
    return ("fresh",
            f"'{needle}' newest ledger rows: " + " | ".join(
                f"{r[0]} {r[1]} {r[2]}" for r in rows),
            DEFAULT_MAX_AGE_HOURS)


def probe_balance(row):
    """A row about a prepaid balance or a top-up."""
    text = _text(row).lower()
    if not any(k in text for k in ("balance", "top up", "top-up", "prepaid", "credit limit")):
        return None
    script = "/root/bin/wake-balance.py"
    if not Path(script).exists():
        return ("unknown", "wake-balance.py not found", DEFAULT_MAX_AGE_HOURS)
    try:
        out = subprocess.run(["/usr/bin/python3", script, "--json"],
                             capture_output=True, text=True, timeout=60).stdout
        data = json.loads(out)
    except Exception as exc:  # noqa: BLE001
        return ("unknown", "balance unreadable: %r" % (exc,), DEFAULT_MAX_AGE_HOURS)
    return ("fresh",
            "balance %s, state %s, ceiling/day %s, stop line %s"
            % (data.get("balance"), data.get("state"), data.get("ceiling"), data.get("floor")),
            DEFAULT_MAX_AGE_HOURS)


def probe_flag(row):
    """A row asserting an env flag's state. Read the flag."""
    text = _text(row)
    # TIGHT ON PURPOSE. A looser pattern (\b[A-Z][A-Z0-9_]{6,}\s*=\s*(true|false|0|1), case
    # insensitive) produced two false 'changed' verdicts on real rows the first time this ran:
    # it matched the prose "6.625 percent = 1,700.76" as a flag named PERCENT, and the phrase
    # "MemoryHigh = 12884901888" as a flag named MEMORYHIGH whose value it read as the digit 1.
    # A false 'changed' is worse than no check at all: it amends a correct row and teaches the
    # owner to distrust the marker. So: the name must be UPPERCASE, must contain at least one
    # underscore, and the value must be a WHOLE token.
    m = re.search(
        r"\b([A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+)\s*=\s*(true|false|0|1)(?![0-9A-Za-z_])", text)
    if not m:
        return None
    flag, stated = m.group(1), m.group(2).lower()
    env = Path("/opt/company/.env")
    if not env.exists():
        return ("unknown", "%s not found" % env, DEFAULT_MAX_AGE_HOURS)
    live = None
    for line in env.read_text(encoding="utf-8", errors="ignore").splitlines():
        if line.strip().startswith(flag + "="):
            live = line.split("=", 1)[1].strip().lower()
            break
    if live is None:
        return ("changed", f"{flag} is not set in /opt/company/.env; the row asserts "
                           f"{flag}={stated}", DEFAULT_MAX_AGE_HOURS)
    if live != stated:
        return ("changed", f"{flag} now reads {live}; the row asserts {stated}",
                DEFAULT_MAX_AGE_HOURS)
    return ("fresh", f"{flag}={live} confirmed", DEFAULT_MAX_AGE_HOURS)


def _git_repos(limit: int = 60) -> list[str]:
    """Every git repository this host can see, bounded.

    THE FIRST VERSION OF THIS PROBE HARD-CODED THREE PATHS, and on its first real run it
    declared owner-queue row 465's cited evidence "NOT found" - because the file it cites lives
    in a repository that was not on the list. That is the same failure the estate has recorded
    twice ("a path you did not check is not an absence") and the same one I made by hand on
    2026-10-15 with a camera citation I searched for in the wrong repo. A checker that reports
    somebody else's good work as missing is worse than no checker.
    """
    roots = ("/root", "/home", "/opt", "/srv")
    found = []
    for root in roots:
        if not os.path.isdir(root):
            continue
        for dirpath, dirnames, _ in os.walk(root):
            depth = dirpath[len(root):].count(os.sep)
            if depth > 4:
                dirnames[:] = []
                continue
            dirnames[:] = [d for d in dirnames
                           if d not in (".git", "node_modules", ".venv", "__pycache__",
                                        "case-media", "objects")]
            if ".git" in os.listdir(dirpath) if os.path.isdir(dirpath) else False:
                found.append(dirpath)
            if len(found) >= limit:
                return found
    return found


def probe_repo_citation(row):
    """A row citing a git commit and/or a repository path. Does the evidence exist somewhere?

    SEMANTICS, and the distinction is the whole point: FOUND means fresh. NOT FOUND means
    UNKNOWN, never 'changed'. Absence from the repositories a checker happens to enumerate is
    not evidence that a citation is wrong - it is evidence the search was incomplete, and those
    are different sentences. Only a positive contradiction (the file exists and does not contain
    what the row says) would justify 'changed', and this probe cannot establish that.
    """
    text = _text(row)
    m = re.search(r"commit\s+([0-9a-f]{7,40})", text, re.I)
    paths = re.findall(r"((?:docs|scripts|app|research|domains|tools)/[\w./-]+\.(?:md|py|json|ts|sh|csv))", text)
    if not (m or paths):
        return None
    repos = _git_repos()
    found, checked = [], len(repos)
    for repo in repos:
        name = Path(repo).name
        for p in paths[:4]:
            r = subprocess.run(["git", "-C", repo, "cat-file", "-e", "HEAD:%s" % p],
                               capture_output=True, text=True)
            if r.returncode == 0:
                found.append("%s in %s" % (p, name))
        if m:
            r = subprocess.run(["git", "-C", repo, "cat-file", "-t", m.group(1)],
                               capture_output=True, text=True)
            if r.returncode == 0:
                found.append("commit %s in %s" % (m.group(1)[:9], name))
    if found:
        return ("fresh", "cited evidence present: " + "; ".join(sorted(set(found))[:4])
                + " (searched %d repos)" % checked, DEFAULT_MAX_AGE_HOURS)
    return ("unknown",
            "cited evidence NOT FOUND in any of the %d repositories this host can see - which is "
            "NOT proof the citation is wrong, only that the search was incomplete" % checked,
            DEFAULT_MAX_AGE_HOURS)


#: name -> (function, what it measures, may it fire automatically?)
#
#: THE `auto` FLAG IS THE MOST IMPORTANT DESIGN DECISION IN THIS FILE, and it was forced by two
#: real misses in the first hour. Heuristic detection on a row's TEXT produces ADJACENT-QUESTION
#: matches: the word "balance" made a family-tuition row (#169) report the AI credit balance, and
#: made a Chase-card row (#482) report it too; the word "stripe" made a sales-tax row (#465)
#: report Stripe's last ledger charge instead of its own deadline. Every one of those is TRUE and
#: answers a neighbouring question, which is worse than answering none - it looks like evidence.
#:
#: So only probes that re-measure WHAT THE ROW ITSELF ASSERTS, with no external lookup and no
#: ambiguity, may fire automatically. Those are `elapsed` and `deadline`: both parse the row's own
#: text and recompute it against today. Every external-lookup probe fires ONLY when a row says
#: `[probe:NAME]` explicitly, which is a declaration that this probe speaks to THIS row's premise.
#: An untagged row is then honestly `unprobed` - "nobody has said how to re-measure this yet" -
#: which is a number worth driving down by tagging, not by guessing.
PROBES = {
    "elapsed": (probe_elapsed, "a stated 'N days late/old/ago' against a due date", True),
    "deadline": (probe_deadline, "a stated due date", True),
    "provider": (probe_provider, "an AI provider being used or failing", False),
    "merchant": (probe_merchant, "a recurring charge", False),
    "balance": (probe_balance, "a prepaid balance or top-up", False),
    "flag": (probe_flag, "an env flag's state", False),
    "repo-citation": (probe_repo_citation, "a git commit or repository path", False),
}

#: Order matters: the most specific shape wins. elapsed before deadline, because a row stating
#: both is the #492 shape and the elapsed correction is the useful one.
PROBE_ORDER = ("elapsed", "flag", "provider", "merchant", "balance", "repo-citation", "deadline")


def match_probes(row):
    """Which probes speak to this row? An explicit [probe:NAME] always wins; auto only if allowed."""
    text = _text(row)
    explicit = [p for p in re.findall(r"\[probe:\s*([a-z-]+)\s*\]", text, re.I) if p in PROBES]
    if explicit:
        return explicit
    return [name for name in PROBE_ORDER if PROBES[name][2] and _applies(name, row)]


def _applies(name, row):
    try:
        return PROBES[name][0](row) is not None
    except Exception:  # noqa: BLE001 - a probe that raises simply does not apply
        return False


def run_probe(name, row):
    fn = PROBES[name][0]
    try:
        res = fn(row)
    except Exception as exc:  # noqa: BLE001
        return ("unknown", "probe %s raised %r" % (name, exc), DEFAULT_MAX_AGE_HOURS)
    if res is None:
        return ("unprobed", "probe %s had nothing to measure" % name, DEFAULT_MAX_AGE_HOURS)
    return res


def check_row(row):
    """The verdict for one row: the first matching probe that reports changed wins."""
    names = match_probes(row)
    if not names:
        return ("unprobed", "no probe matches this row's shape", DEFAULT_MAX_AGE_HOURS, "none")
    results = [(n,) + run_probe(n, row) for n in names]
    for n, verdict, detail, age in results:
        if verdict == "changed":
            return (verdict, detail, age, n)
    for n, verdict, detail, age in results:
        if verdict == "unknown":
            return (verdict, detail, age, n)
    n, verdict, detail, age = results[0]
    return (verdict, detail, age, n)


# --------------------------------------------------------------------------- #
# sweep and gate
# --------------------------------------------------------------------------- #
def pending_rows(con):
    cols = [r[1] for r in con.execute("PRAGMA table_info(owner_decision_queue)")]
    return [dict(zip(cols, r)) for r in con.execute(
        "SELECT * FROM owner_decision_queue WHERE status='pending' ORDER BY id")]


def amend_row(row_id, note):
    """Amend through the queue's own tool, as an argument list - never a shell."""
    con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
    existing = con.execute("SELECT context FROM owner_decision_queue WHERE id=?",
                           (row_id,)).fetchone()[0] or ""
    con.close()
    marker = "[premise-check %s]" % dt.date.today().isoformat()
    r = subprocess.run(["/usr/bin/python3", QUEUE, "amend", str(row_id),
                        "--context", existing + "\n\n" + marker + " " + note],
                       capture_output=True, text=True)
    return r.returncode == 0, (r.stdout.strip() or r.stderr.strip())


def cmd_sweep(args) -> int:
    con = sqlite3.connect(DB)
    ensure_schema(con)
    rows = pending_rows(con)
    due, done, changed = [], 0, 0
    for row in rows:
        st = last_check(con, row["id"])
        budget = st[5] if st else DEFAULT_MAX_AGE_HOURS
        age = hours_since(st[2]) if st else None
        if age is not None and age < budget:
            continue
        due.append(row)
    print("pending rows: %d   due for re-measurement: %d   (budget %sh)"
          % (len(rows), len(due), DEFAULT_MAX_AGE_HOURS))
    for row in due:
        verdict, detail, budget, probe = check_row(row)
        print("  #%-4s %-9s %-14s %s" % (row["id"], verdict, probe, detail[:110]))
        if args.apply:
            record(con, row["id"], probe, verdict, detail, budget)
            done += 1
            if verdict == "changed":
                ok, out = amend_row(row["id"], "PREMISE MOVED: " + detail)
                print("        amended: %s" % (out if ok else "FAILED " + out))
                changed += 1 if ok else 0
    if not args.apply:
        print("\nDRY RUN - nothing written. Re-run with --apply.")
    else:
        print("\nrecorded %d check(s); %d row(s) amended as moved" % (done, changed))
    con.close()
    return 0


def cmd_check(args) -> int:
    con = sqlite3.connect(DB)
    ensure_schema(con)
    rows = {r["id"]: r for r in pending_rows(con)}
    row = rows.get(args.id)
    if row is None:
        row = con.execute("SELECT * FROM owner_decision_queue WHERE id=?", (args.id,)).fetchone()
        if row is None:
            print("row %s: NOT FOUND" % args.id)
            return 3
        cols = [c[1] for c in con.execute("PRAGMA table_info(owner_decision_queue)")]
        row = dict(zip(cols, row))
    verdict, detail, budget, probe = check_row(row)
    print("#%s  verdict=%s  probe=%s  (budget %sh)" % (args.id, verdict, probe, budget))
    print("   %s" % detail)
    st = last_check(con, args.id)
    if st:
        age = hours_since(st[2])
        print("   last recorded check: %s (%.1fh ago), verdict then: %s"
              % (st[2], age if age is not None else -1, st[3]))
    con.close()
    return 10 if verdict == "changed" else 0


def cmd_gate(args) -> int:
    """Exit 0 if the row may be presented as-is; 10 if its premise has moved."""
    return cmd_check(args)


def cmd_probes(args) -> int:
    print("probes (order = match precedence):")
    for name in PROBE_ORDER:
        print("  %-14s %-9s %s" % (name, "AUTO" if PROBES[name][2] else "explicit",
                                   PROBES[name][1]))
    print("\nAUTO probes re-measure what the row itself asserts, so they may fire on their own.")
    print("The rest need an explicit [probe:NAME] in the row, because a heuristic that fires on a")
    print("neighbouring question looks like evidence and is not.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("sweep", help="re-measure pending rows whose premise is due")
    p.add_argument("--apply", action="store_true", help="write results (default: dry run)")
    p.add_argument("--dry-run", action="store_true",
                   help="explicit no-op flag; dry run is already the default")
    p.set_defaults(fn=cmd_sweep)

    p = sub.add_parser("check", help="verdict for one row, writing nothing")
    p.add_argument("id", type=int)
    p.set_defaults(fn=cmd_check)

    p = sub.add_parser("gate", help="exit 0 = safe to present, 10 = premise moved")
    p.add_argument("id", type=int)
    p.set_defaults(fn=cmd_gate)

    p = sub.add_parser("probes", help="list the probes")
    p.set_defaults(fn=cmd_probes)

    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
