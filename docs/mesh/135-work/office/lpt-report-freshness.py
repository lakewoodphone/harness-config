#!/usr/bin/env python3
"""lpt-report-freshness.py - did the weekly money/customer report run, and is what it
reads still alive?

WHY THIS EXISTS. The owner's requirement, 2026-10-08: *"we really have to keep track of
this long-term"*. The shop's money/customer reporting went FIVE WEEKS without running and
nothing anywhere noticed, because the only component that could have noticed was the
component that had stopped. A tracking system that can silently die is not tracking
anything. Measured that week: the last consolidated business analysis was 2026-09-01, the
only runner was a PowerShell file that cannot run on the authority, and no state anywhere
was older than the one manual run - so there was nothing for a reader to be wrong about.

THE PATTERN IS COPIED, DELIBERATELY, from `~/bin/lpt-audit-freshness.py` (the estate's
working answer to exactly this failure, written 2026-10-07), and for the same reason it
gives: this check runs DAILY while the job it watches runs WEEKLY, because a guard that
runs *inside* the weekly job cannot report that the weekly job never ran. It reads the
watched job's own newest state, and on staleness files ONE deduplicated row in the owner
decision queue instead of repeating itself every day. The differences here are (a) three
questions instead of one, and (b) a reader's own distinction between "stale" and "could
not measure", both of which are described below.

THE THREE QUESTIONS - asked separately, never conflated, because each has its own fix:

  1. DID THE PIPELINE RUN?     newest report artefact under ~/.lpt-reports/
                               (`scripts/lpt-business-report.sh` writes
                               business-report-YYYY-MM-DD.md and manifest-*.tsv per run)
                               threshold: 9 days (a weekly job plus a day of slack).
  2. DID THE LONG-TERM STORE ADVANCE?  newest `capture_run` in ~/.lpt-reports/tracking.db,
                               read on `ingested_at_utc` (whether rows are still being
                               written), and also reported on `observed_at_utc` (the moment
                               the numbers describe), so a store that is being written from
                               back-dated artefacts is not mistaken for a live feed.
                               threshold: 9 days. A pipeline that exits 0 but records
                               nothing is still broken, and only this question catches it.
  3. ARE THE SOURCES ALIVE?    the accounting DB's last Plaid sync, the production DB's
                               newest order, and the local Dialpad tables' newest SMS and
                               call. A report drawn from a dead feed must fail here even if
                               the runner exited 0.
                               thresholds: Plaid sync 36h (one missed daily sync - the
                               analytics engine's own DEFAULT_MAX_STORE_AGE_H), Dialpad SMS
                               36h / calls 48h (the engine's own gate: SMS is daily, the call
                               harvest runs every 30 min), production orders 96h (orders are
                               not a high-frequency feed and a shop can genuinely close for a
                               long weekend, so the guard must not cry wolf on quiet days).

THREE OUTCOMES, NEVER THE SAME THING:
  * fresh           - every question answered and within its threshold. exit 0.
  * stale           - a named, dated reason, quoting the reading and its age. exit 1.
  * could not measure - the CHECK ITSELF failed (the store is absent or unreadable, a table
                      is gone, the production DB could not be reached). exit 1 and says so.
                      An empty result is not evidence of health, so it is never reported as
                      fresh; and it is never reported as "stale" either, because that would
                      invent a date we did not read. Check-level status is kept per question
                      so a dead production link does not hide a healthy pipeline.

WHAT IT DOES NOT DO. It never writes to a production database (every connection is opened
read-only), never sends anything to anyone, and never files an owner-queue row unless
`--file` is passed. By default it only prints and writes its own status file.

USAGE
  scripts/lpt-report-freshness.py                 # the real system, print + write status
  scripts/lpt-report-freshness.py --json          # the same reading as JSON
  scripts/lpt-report-freshness.py --file          # also file ONE queue row if not fresh
  scripts/lpt-report-freshness.py --simulate-stale-days 40
                                                  # pretend now is 40 days later, to prove
                                                  # the stale path; never files a row
Exit codes: 0 fresh, 1 stale or could-not-measure, 2 usage error.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sqlite3
import subprocess
import sys
from dataclasses import dataclass, field

STAMP_FMT = "%Y%m%dT%H%M%SZ"

HOME = pathlib.Path.home()
REPORTS_ROOT = HOME / ".lpt-reports"
TRACKING_DB = REPORTS_ROOT / "tracking.db"
STATUS_PATH = REPORTS_ROOT / "freshness.json"
MARKER_PATH = REPORTS_ROOT / "freshness-reported.txt"
QUEUE = HOME / "bin" / "owner-queue.py"

# --- thresholds (days unless the constant says hours) ------------------------
MAX_PIPELINE_AGE_D = 9.0     # weekly job + 1 day of slack, same convention as lpt-audit-freshness
MAX_STORE_AGE_D = 9.0        # the store advances with the pipeline, so it gets the same window
MAX_PLAID_SYNC_AGE_H = 36.0  # daily Plaid sync; matches lpt_analytics.today.DEFAULT_MAX_STORE_AGE_H
MAX_SMS_AGE_H = 36.0         # the engine's own dialpad gate (SMS: daily feed)
MAX_CALL_AGE_H = 48.0        # the engine's own dialpad gate (calls: 30-minute harvest)
MAX_ORDER_AGE_H = 96.0       # production orders: low frequency, do not cry wolf on a weekend

FRESH, STALE, UNMEASURABLE = "fresh", "stale", "unmeasurable"


@dataclass
class Check:
    """One answered question. `age` is None only when the check could not measure."""

    name: str
    status: str
    reason: str
    observed: str | None = None
    age: float | None = None      # days
    max_age: float | None = None  # days
    extra: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "status": self.status,
            "reason": self.reason,
            "observed": self.observed,
            "age_days": None if self.age is None else round(self.age, 2),
            "max_age_days": self.max_age,
            **self.extra,
        }


# --------------------------------------------------------------------------
# time helpers
# --------------------------------------------------------------------------
def parse_ts(value) -> dt.datetime | None:
    """Parse an ISO timestamp that may carry Z, +00:00, seconds or milliseconds."""
    if value is None:
        return None
    try:
        s = str(value).strip()
        if not s:
            return None
        if s.isdigit():  # epoch seconds or milliseconds
            n = int(s)
            if n > 1_000_000_000_000:
                n = n / 1000.0
            return dt.datetime.fromtimestamp(n, tz=dt.timezone.utc)
        d = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=dt.timezone.utc)
        return d.astimezone(dt.timezone.utc)
    except Exception:  # noqa: BLE001 - an unparseable timestamp is "not measured"
        return None


def format_age(days: float | None) -> str:
    """The compact age for the summary column: minutes, hours, days, then one decimal."""
    if days is None:
        return "n/a"
    minutes = days * 1440.0
    if minutes < 60.0:
        return f"{max(1.0, minutes):.0f}m"
    if days < 1.0:
        return f"{days * 24:.0f}h"
    if days <= 60.0:
        return f"{round(days)}d" if abs(days - round(days)) < 0.05 else f"{days:.0f}d"
    return f"{days:.1f}d"


def format_age_words(days: float | None) -> str:
    """The age as a sentence fragment: '40 days', '19.9 hours', '12 minutes'.

    Used inside the reason text, where 'max 9d' is unreadable prose and 'now ago' is not a
    sentence. Never returns an empty or non-numeric string, so a reason always carries an age.
    """
    if days is None:
        return "an unreadable age"
    minutes = days * 1440.0
    if minutes < 90.0:
        n = max(1.0, round(minutes))
        return f"{n:.0f} minute" + ("" if n == 1 else "s")
    hours = days * 24.0
    if hours < 24.0:
        return f"{hours:.1f} hour" + ("s" if round(hours, 1) != 1.0 else "")
    n = days if abs(days - round(days)) >= 0.05 else float(round(days))
    return f"{n:.0f} day" + ("s" if round(n) != 1 else "")


def age_days(when: dt.datetime | None, now: dt.datetime) -> float | None:
    if when is None:
        return None
    return (now - when).total_seconds() / 86400.0


def _stamp_from_name(path: pathlib.Path, prefix: str, suffix: str) -> dt.datetime | None:
    """UTCT stamp embedded in a report filename, e.g. manifest-20261008T231905Z.tsv.

    Parsing the name rather than using mtime is deliberate: mtime is rewritten by a copy
    or a touch, and reading the artefact's own stamp is the same rule the tracking store
    uses (observed_at, not ingested_at).
    """
    name = path.name
    if not (name.startswith(prefix) and name.endswith(suffix)):
        return None
    raw = name[len(prefix): len(name) - len(suffix)]
    try:
        return dt.datetime.strptime(raw, STAMP_FMT).replace(tzinfo=dt.timezone.utc)
    except ValueError:
        return None


def _date_from_name(path: pathlib.Path, prefix: str, suffix: str) -> dt.datetime | None:
    """`business-report-2026-10-08.md` -> that date, as UTC midnight."""
    name = path.name
    if not (name.startswith(prefix) and name.endswith(suffix)):
        return None
    raw = name[len(prefix): len(name) - len(suffix)]
    try:
        d = dt.datetime.strptime(raw, "%Y-%m-%d")
        return d.replace(tzinfo=dt.timezone.utc)
    except ValueError:
        return None


def _readonly(path: pathlib.Path) -> sqlite3.Connection:
    """Open an existing SQLite file read-only. Missing file raises - that is the point."""
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=15.0)
    conn.row_factory = sqlite3.Row
    return conn


# --------------------------------------------------------------------------
# question 1 - did the pipeline run?
# --------------------------------------------------------------------------
def check_pipeline(root: pathlib.Path, now: dt.datetime, max_age_days: float) -> Check:
    name = "pipeline ran (newest report artefact)"
    if not root.exists():
        return Check(name, STALE, f"no report directory at {root} - the pipeline has never "
                                  f"produced anything", None, None, max_age_days)

    summaries = [p for p in root.glob("*/business-report-*.md") if p.is_file()]
    manifests = [p for p in root.glob("*/manifest-*.tsv") if p.is_file()]

    best_path, best_day = None, None
    for path in summaries:
        day = _date_from_name(path, "business-report-", ".md")
        if day and (best_day is None or day > best_day):
            best_path, best_day = path, day
    if best_day is None:
        for path in manifests:
            when = _stamp_from_name(path, "manifest-", ".tsv")
            if when and (best_day is None or when.date() > best_day.date()):
                best_path, best_day = path, when

    extra = {"summaries": len(summaries), "manifests": len(manifests)}

    if best_day is None:
        detail = (f"no report artefact under {root}" if not (manifests or summaries)
                  else f"{len(manifests)} manifest(s) and {len(summaries)} summary file(s) exist "
                       f"under {root} but none carries a parseable date")
        return Check(name, STALE, detail, None, None, max_age_days, extra)

    # The artefact's own stamp carries a DATE, not a clock time, so the age is counted in whole
    # calendar days. Reporting 12.5 days from a date-only stamp would invent a half-day of
    # precision the evidence does not have.
    age = float((now.date() - best_day.date()).days)
    extra["newest_artefact"] = str(best_path.relative_to(root))
    extra["has_summary"] = best_path.suffix == ".md"
    if best_path.suffix != ".md":
        # A manifest with no summary on that day means the run started and never finished
        # (the summary is written last). Say so - it is a different fault from a missing run.
        extra["note"] = ("newest artefact is a manifest with no summary beside it - that run "
                         "started and did not finish")

    if age > max_age_days:
        return Check(name, STALE,
                     f"newest report is {best_path.name} dated {best_day.date().isoformat()} "
                     f"({format_age_words(age)} old, max {max_age_days:.0f} days)",
                     best_day.date().isoformat(), age, max_age_days, extra)
    return Check(name, FRESH,
                 f"newest report is {best_path.name} dated {best_day.date().isoformat()} "
                 f"({format_age_words(age)} old, max {max_age_days:.0f} days)",
                 best_day.date().isoformat(), age, max_age_days, extra)


# --------------------------------------------------------------------------
# question 2 - did the long-term store advance?
# --------------------------------------------------------------------------
def check_tracking_store(db: pathlib.Path, now: dt.datetime, max_age_days: float) -> Check:
    name = "long-term store advanced (newest capture_run)"
    if not db.exists():
        return Check(name, UNMEASURABLE,
                     f"the tracking store {db} does not exist, so nothing can say whether "
                     f"captures are still being written", None, None, max_age_days)
    try:
        conn = _readonly(db)
        try:
            row = conn.execute(
                "SELECT MAX(ingested_at_utc) AS ing, MAX(observed_at_utc) AS obs, "
                "COUNT(*) AS n FROM capture_run"
            ).fetchone()
            total = int(row["n"] or 0)
            newest_ing = parse_ts(row["ing"])
            newest_obs = parse_ts(row["obs"])
        finally:
            conn.close()
    except sqlite3.Error as exc:
        return Check(name, UNMEASURABLE,
                     f"could not read {db} ({type(exc).__name__}: {exc})",
                     None, None, max_age_days)
    except Exception as exc:  # noqa: BLE001
        return Check(name, UNMEASURABLE,
                     f"the store check itself failed ({type(exc).__name__}: {exc})",
                     None, None, max_age_days)

    extra: dict = {"capture_rows": total}
    if total == 0:
        return Check(name, STALE, "the store exists and holds no capture_run rows at all",
                     None, None, max_age_days, extra)
    if newest_ing is None:
        return Check(name, UNMEASURABLE,
                     f"the store holds {total} capture_run row(s) and no readable ingested_at_utc",
                     None, None, max_age_days, extra)

    age = age_days(newest_ing, now)
    extra.update({
        "newest_ingested_at_utc": newest_ing.isoformat().replace("+00:00", "Z"),
        "newest_observed_at_utc": (newest_obs.isoformat().replace("+00:00", "Z")
                                   if newest_obs else None),
        "newest_capture_age_days": None if newest_obs is None else round(age_days(newest_obs, now), 2),
    })
    if age is not None and age > max_age_days:
        return Check(name, STALE,
                     f"newest capture was ingested {newest_ing.date().isoformat()} "
                     f"({format_age_words(age)} ago, max {max_age_days:.0f} days) - the pipeline may run but "
                     f"nothing is being recorded",
                     newest_ing.isoformat(), age, max_age_days, extra)
    return Check(name, FRESH,
                 f"newest capture was ingested {newest_ing.date().isoformat()} "
                 f"({format_age_words(age)} ago, max {max_age_days:.0f} days); {total} capture(s) on record",
                 newest_ing.isoformat(), age, max_age_days, extra)


# --------------------------------------------------------------------------
# question 3 - are the sources alive?
# --------------------------------------------------------------------------
def check_accounting_plaid(db: pathlib.Path, now: dt.datetime, max_age_h: float) -> Check:
    name = "source: accounting Plaid sync"
    if not db.exists():
        return Check(name, UNMEASURABLE, f"accounting DB {db} does not exist", None, None,
                     max_age_h / 24.0)
    try:
        conn = _readonly(db)
        try:
            row = conn.execute(
                "SELECT created_at FROM source_documents "
                "WHERE source_path LIKE 'plaid://sync/%' ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        return Check(name, UNMEASURABLE,
                     f"could not read {db} ({type(exc).__name__}: {exc})", None, None,
                     max_age_h / 24.0)
    when = parse_ts(row["created_at"]) if row else None
    if when is None:
        return Check(name, UNMEASURABLE,
                     f"no readable 'plaid://sync/%' row in source_documents of {db} - either the "
                     f"sync never ran or the record is missing", None, None, max_age_h / 24.0)
    age_h = (now - when).total_seconds() / 3600.0
    if age_h > max_age_h:
        return Check(name, STALE,
                     f"last Plaid sync was {when.date().isoformat()} ({age_h:.1f}h ago, "
                     f"max {max_age_h:.0f}h) - landed money cannot be trusted",
                     when.isoformat(), age_h / 24.0, max_age_h / 24.0)
    return Check(name, FRESH,
                 f"last Plaid sync was {when.date().isoformat()} ({age_h:.1f}h ago, "
                 f"max {max_age_h:.0f}h)",
                 when.isoformat(), age_h / 24.0, max_age_h / 24.0)


def _dialpad_max(conn: sqlite3.Connection, table: str, column: str) -> dt.datetime | None:
    row = conn.execute(f"SELECT MAX({column}) AS m FROM {table}").fetchone()
    return parse_ts(row["m"]) if row else None


def check_dialpad(db: pathlib.Path, now: dt.datetime, max_sms_h: float,
                  max_call_h: float) -> list[Check]:
    """Two named checks, not one: SMS and calls fail for different reasons."""
    sms = Check("source: dialpad SMS feed", UNMEASURABLE, "", None, None, max_sms_h / 24.0)
    calls = Check("source: dialpad call feed", UNMEASURABLE, "", None, None, max_call_h / 24.0)
    if not db.exists():
        why = f"secretary DB {db} does not exist"
        sms.reason = calls.reason = why
        return [sms, calls]
    try:
        conn = _readonly(db)
        try:
            sms_when = _dialpad_max(conn, "dialpad_sms_cache", "created_at")
            call_when = _dialpad_max(conn, "dialpad_call_full", "date_started_ms")
        finally:
            conn.close()
    except sqlite3.Error as exc:
        why = f"could not read dialpad tables in {db} ({type(exc).__name__}: {exc})"
        sms.reason = calls.reason = why
        return [sms, calls]
    except Exception as exc:  # noqa: BLE001
        why = f"the dialpad check itself failed ({type(exc).__name__}: {exc})"
        sms.reason = calls.reason = why
        return [sms, calls]

    for check, when, max_h, label in ((sms, sms_when, max_sms_h, "SMS"),
                                      (calls, call_when, max_call_h, "call")):
        if when is None:
            check.status = UNMEASURABLE
            check.reason = f"the {label} table is empty or holds no readable timestamp"
            continue
        age_h = (now - when).total_seconds() / 3600.0
        check.observed = when.isoformat()
        check.age = age_h / 24.0
        if age_h > max_h:
            check.status = STALE
            check.reason = (f"newest {label} is {when.date().isoformat()} ({age_h:.1f}h ago, "
                            f"max {max_h:.0f}h)")
        else:
            check.status = FRESH
            check.reason = (f"newest {label} is {when.date().isoformat()} ({age_h:.1f}h ago, "
                            f"max {max_h:.0f}h)")
    return [sms, calls]


def default_prod_reader(db_url: str | None = None) -> tuple[dt.datetime | None, str]:
    """`(newest production order createdAt, note)` - never raises, never invents a time.

    The note is a short human string; a caller that gets `None` must treat the source as
    unmeasured, not as healthy. The connection string is never included in output.
    """
    try:
        import psycopg2  # noqa: PLC0415 - optional dependency, imported on use
    except Exception as exc:  # noqa: BLE001
        return None, f"psycopg2 unavailable ({type(exc).__name__})"
    url = db_url
    if not url:
        try:
            sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / "finance"))
            from lpt_analytics import config  # noqa: PLC0415
            url = config.load_database_url()
        except Exception as exc:  # noqa: BLE001
            return None, f"no production URL ({type(exc).__name__}: {exc})"
    try:
        conn = psycopg2.connect(url, connect_timeout=15)
        try:
            cur = conn.cursor()
            cur.execute('SELECT MAX("createdAt") FROM orders')
            row = cur.fetchone()
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001
        return None, f"production DB unreachable ({type(exc).__name__}: {exc})"
    return parse_ts(row[0] if row else None), "ok"


def check_production_orders(now: dt.datetime, max_age_h: float,
                            reader=None) -> Check:
    name = "source: production orders"
    reader = reader or default_prod_reader
    try:
        when, note = reader()
    except Exception as exc:  # noqa: BLE001
        return Check(name, UNMEASURABLE, f"the production check itself failed "
                                         f"({type(exc).__name__}: {exc})", None, None,
                     max_age_h / 24.0)
    if when is None:
        return Check(name, UNMEASURABLE,
                     f"{note} - no production order timestamp could be read", None, None,
                     max_age_h / 24.0)
    age_h = (now - when).total_seconds() / 3600.0
    if age_h > max_age_h:
        return Check(name, STALE,
                     f"newest order was created {when.date().isoformat()} ({age_h:.1f}h ago, "
                     f"max {max_age_h:.0f}h) - the production feed has gone quiet",
                     when.isoformat(), age_h / 24.0, max_age_h / 24.0)
    return Check(name, FRESH,
                 f"newest order was created {when.date().isoformat()} ({age_h:.1f}h ago, "
                 f"max {max_age_h:.0f}h)", when.isoformat(), age_h / 24.0, max_age_h / 24.0)


# --------------------------------------------------------------------------
# queue filing - AT MOST ONE row, deduplicated by the reading that caused it
# --------------------------------------------------------------------------
def build_queue_row(bad: list[dict], verdict: str, now: dt.datetime) -> dict:
    """ONE row covering the whole episode: the questions that failed, and what each means.

    `bad` is the JSON form of the failing checks (`Check.as_dict()`), so this can be built
    from a reading that was already written to the status file.
    """
    lines = []
    for c in bad:
        lines.append(f"- {c['name']}: {c['reason']} [{c['status']}]")
    if verdict == "unmeasurable":
        lead = "The money/customer reporting check could not measure part of the system"
    else:
        lead = "The money/customer report has gone stale"
    question = f"{lead} - run the pipeline by hand and re-arm it?"
    context = ("`scripts/lpt-business-report.sh` is scheduled weekly on the authority "
               "(crontab `35 5 * * 0`) and this daily check reads what it leaves behind. "
               "A stopped job cannot complain about itself, which is why this runs daily "
               "while the report runs weekly. The reading at "
               f"{now.strftime(STAMP_FMT)} UTC:\n" + "\n".join(lines) +
               "\nNothing in this check writes to production; it is a liveness check only.")
    return {
        "question": question,
        "context": context,
        "options": ["Run the pipeline by hand now and re-arm the schedule (Recommended)",
                    "Leave it and tell me when it matters",
                    "Turn the schedule off and run the report on demand"],
        "recommendation": ("Run it by hand once and re-arm. The pipeline is read-only, so "
                           "running it costs nothing but the time, and the only cost of the "
                           "check running is the cost of knowing."),
        "severity": "high",
        "blocks": ("Nothing today - but every day it stays stale is a day of money and customer "
                   "movement that was never recorded and cannot be reconstructed"),
        "source": "lpt-report-freshness %s" % now.strftime(STAMP_FMT),
    }


def file_queue_row(row: dict, do_file: bool, queue: pathlib.Path = QUEUE) -> str:
    """`--from-json` is the safe path (P265): the text never passes through a shell."""
    if not do_file:
        return "not filed (no --file)"
    if not queue.exists():
        return f"not filed (no owner-queue.py at {queue})"
    tmp = pathlib.Path("/tmp/lpt-report-freshness.json")
    tmp.write_text(json.dumps(row))
    try:
        r = subprocess.run(["python3", str(queue), "add", "--from-json", str(tmp)],
                           capture_output=True, text=True)
        return (r.stdout or r.stderr or "").strip()[:300] or "filed"
    finally:
        if tmp.exists():
            tmp.unlink()


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------
def run_checks(*, root: pathlib.Path = REPORTS_ROOT, tracking_db: pathlib.Path = TRACKING_DB,
               accounting_db: pathlib.Path | None = None, secretary_db: pathlib.Path | None = None,
               now: dt.datetime | None = None, max_pipeline_days: float = MAX_PIPELINE_AGE_D,
               max_store_days: float = MAX_STORE_AGE_D,
               max_plaid_h: float = MAX_PLAID_SYNC_AGE_H, max_sms_h: float = MAX_SMS_AGE_H,
               max_call_h: float = MAX_CALL_AGE_H, max_order_h: float = MAX_ORDER_AGE_H,
               prod_reader=None) -> tuple[list[Check], dt.datetime]:
    """Every question, asked independently. Returns (checks, the `now` actually used)."""
    now = now or dt.datetime.now(tz=dt.timezone.utc)
    if accounting_db is None or secretary_db is None:
        try:
            sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / "finance"))
            from lpt_analytics import config  # noqa: PLC0415
            if accounting_db is None:
                accounting_db = pathlib.Path(config.ACCOUNTING_DB)
            if secretary_db is None:
                secretary_db = pathlib.Path(config.SECRETARY_DB)
        except Exception:  # noqa: BLE001 - fall back to the documented defaults
            accounting_db = accounting_db or (HOME / "accounting-data" / "live" / "accounting.db")
            secretary_db = secretary_db or pathlib.Path(__file__).resolve().parents[1] / "data" / "secretary.db"

    checks = [check_pipeline(root, now, max_pipeline_days),
              check_tracking_store(tracking_db, now, max_store_days),
              check_accounting_plaid(accounting_db, now, max_plaid_h)]
    checks.extend(check_dialpad(secretary_db, now, max_sms_h, max_call_h))
    checks.append(check_production_orders(now, max_order_h, prod_reader))
    return checks, now


def verdict_of(checks: list[Check]) -> str:
    """Unmeasurable wins over stale: a check that failed did not read a date, so calling it
    'stale' would invent one, and calling it fresh would be the silent false green."""
    if any(c.status == UNMEASURABLE for c in checks):
        return "unmeasurable"
    if any(c.status == STALE for c in checks):
        return STALE
    return FRESH


def question_status(checks: list[Check], indexes: list[int]) -> str:
    """Question 1 and 2 are one check each; question 3 is the source checks together
    (unmeasurable wins over stale, exactly as `verdict_of` decides)."""
    group = [checks[i] for i in indexes]
    if any(c.status == UNMEASURABLE for c in group):
        return UNMEASURABLE
    if any(c.status == STALE for c in group):
        return STALE
    return FRESH


def summarise(checks: list[Check], verdict: str, exit_code: int) -> str:
    lines = ["lpt-report-freshness: %s" % verdict.upper()]
    for c in checks:
        lines.append(f"  [{c.status:^12}] {c.name:38s} {format_age(c.age):>5s}  {c.reason}")
    bad = [c for c in checks if c.status != FRESH]
    if not bad:
        lines.append("  all three questions answered and current: the pipeline ran, the store "
                     "advanced, and every source is alive.")
    lines.append("  exit %d" % exit_code)
    return "\n".join(lines)


def decide_action(result: dict, marker: pathlib.Path, now: dt.datetime, *, do_file: bool,
                  queue: pathlib.Path = QUEUE) -> int:
    """Settle the action/exit code and (only when `do_file`) file at most ONE queue row.

    The dedup key is the set of questions that are not fresh, so a stale reading is filed
    once, a recovery clears the marker, and a *different* fault files again rather than
    being swallowed by the previous episode's marker.
    """
    bad = [c for c in result["checks"] if c["status"] != FRESH]
    key = ",".join(f"{c['name']}={c['status']}" for c in bad) or "FRESH"

    if result["verdict"] == FRESH:
        if marker.exists():
            marker.unlink()  # recovery is a fact worth clearing the marker for
        result["action"] = "fresh"
        return 0
    if marker.exists() and marker.read_text().strip() == key:
        result["action"] = "already-reported"
        return 1
    row = build_queue_row(bad, result["verdict"], now)
    result["action"] = "reported" if do_file else "would-report"
    result["queue"] = file_queue_row(row, do_file, queue)
    if not do_file:
        result["queue_row_preview"] = row
    if do_file:
        marker.parent.mkdir(parents=True, exist_ok=True)
        try:
            marker.write_text(key)
        except OSError as exc:  # a marker we cannot write files every day - say so loudly
            result["marker_error"] = f"{type(exc).__name__}: {exc}"
    return 1


def write_status(result: dict, status: pathlib.Path) -> pathlib.Path:
    status.parent.mkdir(parents=True, exist_ok=True)
    status.write_text(json.dumps(result, indent=1) + "\n")
    return status


def main(argv: list[str] | None = None, prod_reader=None,
         now: dt.datetime | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Did the weekly money/customer report run, and are its sources alive?")
    p.add_argument("--root", default=str(REPORTS_ROOT), help="~/.lpt-reports equivalent")
    p.add_argument("--tracking-db", default=str(TRACKING_DB))
    p.add_argument("--accounting-db", default=None)
    p.add_argument("--secretary-db", default=None)
    p.add_argument("--status", default=str(STATUS_PATH), help="where to write the JSON reading")
    p.add_argument("--marker", default=str(MARKER_PATH),
                   help="what this check last reported, so a stale reading is filed once")
    p.add_argument("--max-pipeline-days", type=float, default=MAX_PIPELINE_AGE_D)
    p.add_argument("--max-store-days", type=float, default=MAX_STORE_AGE_D)
    p.add_argument("--max-plaid-hours", type=float, default=MAX_PLAID_SYNC_AGE_H)
    p.add_argument("--max-sms-hours", type=float, default=MAX_SMS_AGE_H)
    p.add_argument("--max-call-hours", type=float, default=MAX_CALL_AGE_H)
    p.add_argument("--max-order-hours", type=float, default=MAX_ORDER_AGE_H)
    p.add_argument("--simulate-stale-days", type=float, default=0.0,
                   help="pretend now is N days later, to prove the stale path; forces --no-file")
    p.add_argument("--file", action="store_true",
                   help="actually file ONE owner-queue row when not fresh (default: never)")
    p.add_argument("--json", action="store_true", help="print the reading as JSON")
    p.add_argument("--quiet", action="store_true")
    a = p.parse_args(argv)

    # `--simulate-stale-days` is a rehearsal: it must be able to show the stale verdict
    # WITHOUT touching the owner's queue, so it cannot be combined with --file.
    simulated = a.simulate_stale_days > 0
    if simulated and a.file:
        print("lpt-report-freshness: --simulate-stale-days is a rehearsal and cannot be "
              "combined with --file", file=sys.stderr)
        return 2
    do_file = bool(a.file) and not simulated

    now = (now or dt.datetime.now(tz=dt.timezone.utc)) + dt.timedelta(days=a.simulate_stale_days)
    root, marker = pathlib.Path(a.root), pathlib.Path(a.marker)

    checks, now = run_checks(
        root=root, tracking_db=pathlib.Path(a.tracking_db),
        accounting_db=pathlib.Path(a.accounting_db) if a.accounting_db else None,
        secretary_db=pathlib.Path(a.secretary_db) if a.secretary_db else None,
        now=now, max_pipeline_days=a.max_pipeline_days, max_store_days=a.max_store_days,
        max_plaid_h=a.max_plaid_hours, max_sms_h=a.max_sms_hours,
        max_call_h=a.max_call_hours, max_order_h=a.max_order_hours, prod_reader=prod_reader)

    verdict = verdict_of(checks)

    # Position is fixed by run_checks: 0 pipeline, 1 store, 2..5 the source checks.
    result = {
        "at": now.strftime(STAMP_FMT),
        "rehearsal": bool(simulated),
        "simulated_days": a.simulate_stale_days or None,
        "verdict": verdict,
        "questions": {
            "did_the_pipeline_run": question_status(checks, [0]),
            "did_the_store_advance": question_status(checks, [1]),
            "are_the_sources_alive": question_status(checks, [2, 3, 4, 5]),
        },
        "stale": [c.reason for c in checks if c.status == STALE],
        "could_not_measure": [c.reason for c in checks if c.status == UNMEASURABLE],
        "checks": [c.as_dict() for c in checks],
        "thresholds": {
            "pipeline_days": a.max_pipeline_days,
            "store_days": a.max_store_days,
            "plaid_hours": a.max_plaid_hours,
            "sms_hours": a.max_sms_hours,
            "call_hours": a.max_call_hours,
            "orders_hours": a.max_order_hours,
        },
        "action": "none",
    }

    exit_code = decide_action(result, marker, now, do_file=do_file)

    # The reading is written for a human or another job even when nothing else happened.
    write_status(result, pathlib.Path(a.status))

    if a.json:
        print(json.dumps(result, indent=1))
    elif not a.quiet:
        banner = "  REHEARSAL: now is simulated %+.0f day(s) ahead; nothing was filed.\n" % a.simulate_stale_days if simulated else ""
        print(banner + summarise(checks, verdict, exit_code))
        print("  status file: %s" % a.status)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
