#!/usr/bin/env python3
"""Guard tests for the wake queue - one test per guard in CONTRACT.md section 4.

RUN IT
    python3 scripts/wake/tests/test_guards.py
It prints exactly one line per guard, `OK  <guard>` or `FAIL <guard>: <why>`,
then `ALL OK` and exits 0 only if every guard passed.

WHAT MAKES THESE TESTS WORTH ANYTHING
    * Every test drives the REAL CLI in a subprocess - no importing wake.py and
      calling helpers, because the contract is a command line.
    * Every test sets SMS_INBOX_DB to a fresh temp file and ASSERTS that it is
      not ~/.sms-inbox/inbox.db, before every single call. A test that can write
      the live store is a test that can wake the machine for nothing.
    * Every test fails if its guard is deleted or its default loosened. That was
      checked by mutation: `scripts/wake/tests/` was run against copies of
      wake.py with each guard individually disabled, and each mutation must turn
      its own line into FAIL. Set WAKE_PY=/path/to/copy/wake.py to re-run the
      suite against a mutant; set WAKE_SMS_INBOX_PY if the copy is not inside
      the repo.
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
WAKE_PY = Path(os.environ.get("WAKE_PY") or (HERE.parent / "wake.py")).resolve()
SMS_ENV = os.environ.get("WAKE_SMS_INBOX_PY") or None
if not SMS_ENV:
    for cand in (HERE.parent.parent / "sms-inbox.py", HERE.parent / "sms-inbox.py"):
        if cand.is_file():
            SMS_ENV = str(cand)
            break

REAL_STORE = (Path.home() / ".sms-inbox" / "inbox.db").resolve()


def fingerprint() -> tuple:
    try:
        st = REAL_STORE.stat()
        return (True, st.st_size, st.st_mtime_ns)
    except OSError:
        return (False, 0, 0)


class Ctx:
    """One temp store per test. Never the real one - checked on every call."""

    def __init__(self, tmp: str, overrides: dict):
        self.tmp = Path(tmp)
        self.db = self.tmp / "inbox.db"
        self.pause = self.tmp / "WAKE_PAUSED"
        self.overrides = dict(overrides)

    def env(self, **kw) -> dict:
        env = {k: v for k, v in os.environ.items() if not k.startswith("WAKE_")}
        env["SMS_INBOX_DB"] = str(self.db)
        env["WAKE_PAUSE_FILE"] = str(self.pause)
        env["PYTHONIOENCODING"] = "utf-8"
        # Keep whatever store root the harness was pointed at, so a mutant copy
        # of wake.py outside the repo can still find sms-inbox.py.
        env["WAKE_SMS_INBOX_PY"] = kw.pop("_sms_inbox", SMS_ENV or "")
        env.update({k: str(v) for k, v in self.overrides.items()})
        env.update({k: str(v) for k, v in kw.items() if v is not None})
        got = Path(env["SMS_INBOX_DB"]).resolve()
        check(got != REAL_STORE, f"test store {got} IS the real store {REAL_STORE}")
        check(str(self.tmp) in str(got), f"test store {got} is outside {self.tmp}")
        return env

    def run(self, *args, **kw) -> tuple:
        env = self.env(**kw)
        argv = [str(a) for a in args]
        proc = subprocess.run([sys.executable, str(WAKE_PY), *argv], env=env,
                              capture_output=True, text=True, cwd=str(self.tmp))
        check(proc.returncode == 0,
              f"`{' '.join(argv)}` exited {proc.returncode}: {proc.stderr.strip()[:200]}")
        return proc.stdout.strip(), proc.stderr.strip()

    def json(self, *args, **kw) -> dict:
        out, _ = self.run(*args, **kw)
        shown = " ".join(str(a) for a in args)
        check("\n" not in out, f"`{shown}` wrote more than one line of JSON: {out[:160]!r}")
        try:
            return json.loads(out)
        except ValueError as exc:
            raise AssertionError(f"`{shown}` did not print JSON ({exc}): {out[:160]!r}")

    def py(self, code: str, **kw) -> tuple:
        """Run raw python against this store - for proving that a guard lives in
        the store layer rather than in the CLI."""
        env = self.env(**kw)
        proc = subprocess.run([sys.executable, "-c", code], env=env,
                              capture_output=True, text=True, cwd=str(self.tmp))
        check(proc.returncode == 0,
              f"probe exited {proc.returncode}: {proc.stderr.strip()[-300:]}")
        return proc.stdout.strip(), proc.stderr.strip()

    def flag(self, subject, *, prompt="do the thing", env=None, **opts) -> str:
        """`opts` are CLI options (priority=..., source=...); `env` is the
        environment for the call (the caps). Confusing the two is how a test
        ends up exercising nothing, so they are separate names."""
        args = ["flag", "--subject", subject, "--prompt", prompt]
        for key, val in opts.items():
            name = "--" + key.replace("_", "-")
            if val is True:                     # a store_true switch takes no value
                args.append(name)
            elif val is False or val is None:
                continue
            else:
                args += [name, str(val)]
        out, _ = self.run(*args, **(env or {}))
        return out

    def sql(self, query: str, params: tuple = ()) -> list:
        conn = sqlite3.connect(str(self.db), timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            return [dict(r) for r in conn.execute(query, params).fetchall()]
        finally:
            conn.close()

    def row(self, subject: str) -> dict:
        rows = self.sql("SELECT * FROM wake WHERE subject=?", (subject,))
        check(len(rows) == 1, f"expected one wake row for {subject!r}, found {len(rows)}")
        return rows[0]

    def id_of(self, subject: str) -> int:
        return int(self.row(subject)["id"])


def check(cond, why: str) -> None:
    if not cond:
        raise AssertionError(why)


def dt(raw):
    return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))


TESTS: list = []


def guard(name):
    def deco(fn):
        TESTS.append((name, fn))
        return fn
    return deco


# --------------------------------------------------------------------------- #
@guard("dedup")
def test_dedup(ctx: Ctx) -> None:
    """Guard 1: one live row per subject; a second flag is a no-op."""
    check(ctx.flag("dup") == "filed", "the first flag did not file")
    check(ctx.flag("dup", prompt="changed") == "deduped", "a second flag was not deduped")
    rows = ctx.sql("SELECT * FROM wake WHERE subject='dup'")
    check(len(rows) == 1, f"{len(rows)} rows for one subject - the UNIQUE dedup key is gone")
    check(rows[0]["prompt"] == "do the thing",
          "the second flag overwrote the live row's prompt instead of deduping")
    ctx.run("claim", "--by", "tester")
    check(ctx.flag("dup") == "deduped", "a flag against an already-claimed row was not deduped")


@guard("cooldown")
def test_cooldown(ctx: Ctx) -> None:
    """Guard 2: a subject re-filed after a release inside the cooldown is
    suppressed, and the DEFAULT cooldown is not zero."""
    check(ctx.flag("cool") == "filed", "the first flag did not file")
    ctx.run("claim", "--by", "tester")
    ctx.run("finish", str(ctx.id_of("cool")), "--outcome", "done")
    out = ctx.flag("cool")
    check(out == "suppressed:cooldown", f"re-flag after a release printed {out!r}")
    row = ctx.row("cool")
    check(row["not_before"], "suppressed:cooldown left no not_before on the row")
    check(dt(row["not_before"]) > datetime.now(timezone.utc) + timedelta(seconds=60),
          f"not_before {row['not_before']} is not a future cooldown window")
    rel = ctx.json("claim", "--by", "tester")
    check(rel["row"] is None, "a row inside its cooldown was released anyway")

    # The env is honoured, and the default is a real window, not 0.
    kw = dict(WAKE_COOLDOWN_SEC=0)
    check(ctx.flag("cool2", env=kw) == "filed", "with a zero cooldown the flag was not filed")
    ctx.run("claim", "--by", "tester", **kw)
    ctx.run("finish", str(ctx.id_of("cool2")), "--outcome", "done", **kw)
    check(ctx.flag("cool2", env=kw) == "filed",
          "WAKE_COOLDOWN_SEC=0 still suppressed - the env is not read at call time")


@guard("daily-cap")
def test_daily_cap(ctx: Ctx) -> None:
    """Guard 3: at most WAKE_MAX_PER_DAY releases per UTC day."""
    kw = dict(WAKE_MAX_PER_DAY=1)
    check(ctx.flag("day-a", env=kw) == "filed", "flag a did not file")
    check(ctx.flag("day-b", env=kw) == "filed", "flag b did not file")
    first = ctx.json("claim", "--by", "tester", **kw)
    check(first["row"] is not None, "the first release was refused")
    second = ctx.json("claim", "--by", "tester", **kw)
    check(second["row"] is None, "a second release happened past WAKE_MAX_PER_DAY=1")
    check(second.get("blocked_by") == "daily-cap",
          f"the second claim was blocked by {second.get('blocked_by')!r}, not the daily cap")
    st = ctx.json("stats", "--json", **kw)
    check(st["released_today"] == 1, f"released_today={st['released_today']}, expected 1")
    check(any(s.startswith("daily_cap") for s in st["caps_in_force"]),
          f"stats does not report the daily cap in force: {st['caps_in_force']}")
    check("max_per_day" in st["caps"] and st["caps"]["max_per_day"] == 1,
          "stats does not report the value of the daily cap")
    # and the cap really is the env value, not a hard zero
    third = ctx.json("claim", "--by", "tester", WAKE_MAX_PER_DAY=2)
    check(third["row"] is not None, "raising WAKE_MAX_PER_DAY to 2 did not allow the next release")
    # the default itself is the contract's default, not something loosened away
    plain = ctx.json("stats", "--json")
    check(plain["caps"]["max_per_day"] == 8,
          f"the default WAKE_MAX_PER_DAY is {plain['caps']['max_per_day']}, not 8")


@guard("per-source-cap")
def test_per_source_cap(ctx: Ctx) -> None:
    """Guard 4: at most WAKE_MAX_PER_SOURCE_PER_HOUR releases per source per
    rolling hour - and it is PER SOURCE, not a global brake."""
    kw = dict(WAKE_MAX_PER_SOURCE_PER_HOUR=1, WAKE_MAX_PER_DAY=8)
    check(ctx.flag("src-a", source="s1", env=kw) == "filed", "flag a did not file")
    check(ctx.flag("src-b", source="s1", env=kw) == "filed", "flag b did not file")
    check(ctx.flag("src-c", source="s2", env=kw) == "filed", "flag c did not file")
    first = ctx.json("claim", "--by", "tester", **kw)
    check(first["row"] is not None and first["row"]["subject"] == "src-a",
          "the first release was not src-a")
    second = ctx.json("claim", "--by", "tester", **kw)
    check(second["row"] is not None, "source s2 was blocked by s1's cap - it is not per source")
    check(second["row"]["subject"] == "src-c",
          f"the second release was {second['row']['subject']!r}: s1 hit its hourly cap "
          "and was released anyway")
    third = ctx.json("claim", "--by", "tester", **kw)
    check(third["row"] is None, "a second release from the same source inside the hour happened")
    st = ctx.json("stats", "--json", **kw)
    check(any(s.startswith("source_cap") for s in st["caps_in_force"]),
          f"stats does not report the per-source cap in force: {st['caps_in_force']}")
    # the env is the cap, not a hard one
    again = ctx.json("claim", "--by", "tester", WAKE_MAX_PER_SOURCE_PER_HOUR=2, WAKE_MAX_PER_DAY=8)
    check(again["row"] is not None and again["row"]["subject"] == "src-b",
          "raising WAKE_MAX_PER_SOURCE_PER_HOUR to 2 did not release the second s1 row")
    plain = ctx.json("stats", "--json")
    check(plain["caps"]["max_per_source_per_hour"] == 3,
          f"the default WAKE_MAX_PER_SOURCE_PER_HOUR is "
          f"{plain['caps']['max_per_source_per_hour']}, not 3")


@guard("night-gate")
def test_night_gate(ctx: Ctx) -> None:
    """Guard 5: `low` releases only 13:00-03:00 UTC; normal/high always."""
    quiet = dict(WAKE_CLOCK_ISO="2026-01-05T06:00:00+00:00", WAKE_MAX_PER_SOURCE_PER_HOUR=50)
    low = ctx.flag("n-low", priority="low", env=quiet)
    check(low == "filed", f"flagging a low-priority row printed {low!r}")
    rel = ctx.json("claim", "--by", "tester", **quiet)
    check(rel["row"] is None, "a low-priority row was released inside the quiet window")
    check(rel.get("blocked_by") == "night-quiet",
          f"blocked_by={rel.get('blocked_by')!r}, expected the night gate")

    check(ctx.flag("n-normal", priority="normal", env=quiet) == "filed", "normal flag did not file")
    rel = ctx.json("claim", "--by", "tester", **quiet)
    check(rel["row"] is not None and rel["row"]["subject"] == "n-normal",
          "quiet hours blocked a normal-priority release - the gate is not low-only")

    off = dict(quiet, WAKE_NIGHT_QUIET=0)
    rel = ctx.json("claim", "--by", "tester", **off)
    check(rel["row"] is not None and rel["row"]["subject"] == "n-low",
          "WAKE_NIGHT_QUIET=0 did not reopen the quiet window")

    day = dict(WAKE_CLOCK_ISO="2026-01-05T15:00:00+00:00", WAKE_MAX_PER_SOURCE_PER_HOUR=50)
    check(ctx.flag("n-day", priority="low", env=day) == "filed", "daylight low flag did not file")
    rel = ctx.json("claim", "--by", "tester", **day)
    check(rel["row"] is not None and rel["row"]["subject"] == "n-day",
          "a low-priority row was not released at 15:00 UTC")


@guard("kill-switch")
def test_kill_switch(ctx: Ctx) -> None:
    """Guard 6: the pause file stops flagging and releasing, and is never
    deleted by the code that reads it."""
    check(ctx.flag("kill-a") == "filed", "flag a did not file")
    check(ctx.flag("kill-b") == "filed", "flag b did not file")
    ctx.run("claim", "--by", "tester")

    ctx.pause.write_text("paused by the test\n", encoding="utf-8")
    out = ctx.flag("kill-c")
    check(out == "suppressed:paused", f"flag while paused printed {out!r}")
    check(len(ctx.sql("SELECT * FROM wake WHERE subject='kill-c'")) == 0,
          "a row was filed while the kill switch was on")
    rel = ctx.json("claim", "--by", "tester")
    check(rel["row"] is None, "a claim released a row while the kill switch was on")
    check(rel.get("blocked_by") == "paused", f"blocked_by={rel.get('blocked_by')!r}, expected paused")
    check(ctx.pause.exists(), "the kill-switch file was deleted by reading it")

    out, _ = ctx.run("resume")
    check("resumed" in out, f"resume printed {out!r}")
    check(not ctx.pause.exists(), "resume did not remove the kill-switch file")
    check(ctx.flag("kill-d") == "filed", "flagging did not resume after resume")
    rel = ctx.json("claim", "--by", "tester")
    check(rel["row"] is not None and rel["row"]["subject"] == "kill-b",
          "releasing did not resume after resume")


@guard("lease")
def test_lease(ctx: Ctx) -> None:
    """Guard 7: a claim takes a lease, --lease-seconds sets it, and the default
    is a real lease rather than an infinite or zero one."""
    kw = dict(WAKE_MAX_PER_SOURCE_PER_HOUR=50)
    check(ctx.flag("lease-a", env=kw) == "filed", "flag a did not file")
    rel = ctx.json("claim", "--by", "tester", "--lease-seconds", 1, **kw)
    check(rel["row"] is not None, "nothing was released")
    check(rel["row"]["lease_until"], "the claim set no lease_until")
    delta = (dt(rel["row"]["lease_until"]) - datetime.now(timezone.utc)).total_seconds()
    check(-5 <= delta <= 20, f"a 1-second lease is actually {delta:.0f}s")

    check(ctx.flag("lease-b", env=kw) == "filed", "flag b did not file")
    rel = ctx.json("claim", "--by", "tester", **kw)          # no --lease-seconds
    check(rel["row"] is not None, "nothing was released")
    delta = (dt(rel["row"]["lease_until"]) - datetime.now(timezone.utc)).total_seconds()
    check(900 <= delta <= 1500, f"the default lease is {delta:.0f}s, not ~1200s (WAKE_LEASE_SEC)")


@guard("reaper")
def test_reaper(ctx: Ctx) -> None:
    """Guard 8: expired leases go back to new, over-attempted rows fail, old
    rows expire - and running it twice changes nothing the second time."""
    kw = dict(WAKE_MAX_PER_SOURCE_PER_HOUR=50)
    check(ctx.flag("reap-a", env=kw) == "filed", "flag a did not file")
    ctx.run("claim", "--by", "tester", "--lease-seconds", 1, **kw)
    time.sleep(2)
    out = ctx.json("reap", "--json", **kw)
    check(out["requeued"] == 1, f"reap requeued {out['requeued']}, expected 1")
    row = ctx.row("reap-a")
    check(row["state"] == "new", f"an expired lease left the row {row['state']!r}")
    check(row["lease_until"] is None and row["claimed_by"] is None, "reap left the claim attached")

    out = ctx.json("reap", "--json", **kw)
    check((out["requeued"], out["failed"], out["expired"]) == (0, 0, 0),
          f"a second reap was not a no-op: {out}")
    # retire reap-a so the next release cannot pick it up by lowest id
    ctx.run("finish", str(ctx.id_of("reap-a")), "--outcome", "done", **kw)

    check(ctx.flag("reap-c", max_attempts=1, env=kw) == "filed", "flag c did not file")
    rel = ctx.json("claim", "--by", "tester", "--lease-seconds", 1, **kw)
    check(rel["row"] is not None and rel["row"]["subject"] == "reap-c",
          f"the release was {rel['row'] and rel['row']['subject']!r}, expected reap-c")
    time.sleep(2)
    out = ctx.json("reap", "--json", **kw)
    check(out["failed"] == 1, f"reap failed {out['failed']} over-attempted rows, expected 1")
    check(ctx.row("reap-c")["state"] == "failed", "an over-attempted row was not failed")

    old = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat(timespec="seconds")
    conn = sqlite3.connect(str(ctx.db), timeout=10)
    conn.execute("INSERT INTO wake(subject,kind,source,prompt,context,priority,created_at,"
                 "state,attempts,max_attempts) VALUES('reap-old','task','manual','x','',"
                 "'normal',?,'new',0,2)", (old,))
    conn.commit()
    conn.close()
    out = ctx.json("reap", "--json", **kw)
    check(out["expired"] == 1, f"reap expired {out['expired']} rows older than 30 days, expected 1")
    check(ctx.row("reap-old")["state"] == "expired", "a 31-day-old new row was not expired")


@guard("attempt-cap")
def test_attempt_cap(ctx: Ctx) -> None:
    """Guard 9: attempts increments on every claim, the default ceiling is 2,
    and a subject that failed that many times is never retried automatically."""
    kw = dict(WAKE_COOLDOWN_SEC=0, WAKE_MAX_PER_SOURCE_PER_HOUR=50)
    check(ctx.flag("att", env=kw) == "filed", "flag did not file")
    check(ctx.row("att")["max_attempts"] == 2,
          f"the default max_attempts is {ctx.row('att')['max_attempts']}, not 2")
    rel = ctx.json("claim", "--by", "tester", **kw)
    check(rel["row"] is not None and rel["row"]["attempts"] == 1,
          "the first claim did not increment attempts to 1")
    ctx.run("finish", str(ctx.id_of("att")), "--failed", "--outcome", "no good", **kw)

    check(ctx.flag("att", env=kw) == "filed", "a failed row with attempts left was not re-filed")
    rel = ctx.json("claim", "--by", "tester", **kw)
    check(rel["row"] is not None and rel["row"]["attempts"] == 2,
          "the second claim did not increment attempts to 2")
    ctx.run("finish", str(ctx.id_of("att")), "--failed", "--outcome", "no good", **kw)

    out = ctx.flag("att", env=kw)
    check(out == "suppressed:attempts", f"re-filing an exhausted subject printed {out!r}")
    check(ctx.row("att")["state"] == "failed", "an exhausted subject was shuffled back to new")
    rel = ctx.json("claim", "--by", "tester", **kw)
    check(rel["row"] is None, "an exhausted subject was released again")

    # and the ceiling is enforced at claim time too, not only at flag time
    check(ctx.flag("att-2", env=kw) == "filed", "flag att-2 did not file")
    conn = sqlite3.connect(str(ctx.db), timeout=10)
    conn.execute("UPDATE wake SET attempts=2, max_attempts=2, state='new', not_before=NULL,"
                 " claimed_at=NULL, claimed_by=NULL, lease_until=NULL WHERE subject='att-2'")
    conn.commit()
    conn.close()
    rel = ctx.json("claim", "--by", "tester", **kw)
    check(rel["row"] is None, "a row already at its attempt ceiling was released")


@guard("cost-cap")
def test_cost_cap(ctx: Ctx) -> None:
    """Guard 10: finish --cost-usd is recorded, stats reports the day's spend,
    and a day over WAKE_MAX_USD_PER_DAY stops releases."""
    kw = dict(WAKE_MAX_USD_PER_DAY=1.0)
    for subject in ("cost-a", "cost-b", "cost-c"):
        check(ctx.flag(subject, env=kw) == "filed", f"flag {subject} did not file")

    rel = ctx.json("claim", "--by", "tester", **kw)
    check(rel["row"]["subject"] == "cost-a", "cost-a was not released first")
    ctx.run("finish", str(ctx.id_of("cost-a")), "--outcome", "done", "--cost-usd", "0.25", **kw)
    st = ctx.json("stats", "--json", **kw)
    check(abs(st["spend_today_usd"] - 0.25) < 1e-9,
          f"stats reports ${st['spend_today_usd']} after a $0.25 finish")

    rel = ctx.json("claim", "--by", "tester", **kw)
    check(rel["row"] is not None and rel["row"]["subject"] == "cost-b",
          "spending under the cap blocked the next release")
    ctx.run("finish", str(ctx.id_of("cost-b")), "--outcome", "done", "--cost-usd", "1.00", **kw)

    st = ctx.json("stats", "--json", **kw)
    check(abs(st["spend_today_usd"] - 1.25) < 1e-9,
          f"stats reports ${st['spend_today_usd']}, expected $1.25")
    check(any(s.startswith("cost_cap") for s in st["caps_in_force"]),
          f"stats does not report the cost cap in force: {st['caps_in_force']}")
    check(st["caps"]["max_usd_per_day"] == 1.0, "stats does not report the cost cap value")
    rel = ctx.json("claim", "--by", "tester", **kw)
    check(rel["row"] is None, "a release happened on a day already over its spend cap")
    check(rel.get("blocked_by") == "cost-cap", f"blocked_by={rel.get('blocked_by')!r}")
    plain = ctx.json("stats", "--json")
    check(plain["caps"]["max_usd_per_day"] == 3.0,
          f"the default WAKE_MAX_USD_PER_DAY is {plain['caps']['max_usd_per_day']}, not 3.0")


# The authoritative store's `wake` table, exactly as v0 deployed it.
V0_TABLE = """
CREATE TABLE wake (id INTEGER PRIMARY KEY AUTOINCREMENT, subject TEXT NOT NULL UNIQUE,
  kind TEXT NOT NULL DEFAULT 'task', prompt TEXT NOT NULL, context TEXT DEFAULT '',
  priority TEXT NOT NULL DEFAULT 'normal', created_at TEXT NOT NULL,
  state TEXT NOT NULL DEFAULT 'new', claimed_by TEXT, claimed_at TEXT,
  finished_at TEXT, outcome TEXT);
CREATE INDEX IF NOT EXISTS idx_wake_state ON wake(state);
"""
V0_COLUMNS = {"id", "subject", "kind", "prompt", "context", "priority", "created_at",
              "state", "claimed_by", "claimed_at", "finished_at", "outcome"}
# every column section 3 requires, transcribed from the contract not from wake.py
REQUIRED_COLUMNS = ("id", "subject", "kind", "source", "prompt", "context", "priority",
                    "created_at", "not_before", "state", "attempts", "max_attempts",
                    "claimed_by", "claimed_at", "lease_until", "finished_at", "outcome",
                    "cost_usd")


def build_v0_store(ctx: Ctx) -> None:
    """A live v0 table with rows in it - what the authority actually has."""
    conn = sqlite3.connect(str(ctx.db), timeout=10)
    conn.executescript(V0_TABLE)
    conn.execute("INSERT INTO wake(subject,kind,prompt,context,priority,created_at,state)"
                 " VALUES('v0-row','task','old prompt','','normal','2026-09-18T00:00:00+00:00',"
                 "'new')")
    conn.execute("INSERT INTO wake(subject,kind,prompt,context,priority,created_at,state,"
                 "claimed_by,claimed_at) VALUES('v0-claimed','task','p','','normal',"
                 "'2026-09-18T00:00:00+00:00','claimed','old','2026-09-18T00:00:00+00:00')")
    conn.execute("INSERT INTO wake(subject,kind,prompt,context,priority,created_at,state,"
                 "finished_at,outcome) VALUES('v0-done','task','shipped','','normal',"
                 "'2026-09-17T00:00:00+00:00','done','2026-09-17T01:00:00+00:00','shipped it')")
    conn.commit()
    conn.close()


@guard("migration-from-v0")
def test_migration_from_v0(ctx: Ctx) -> None:
    """Not a guard, but the difference between working on the authority and
    crashing there: the live `wake` table is v0, where §3's
    `CREATE TABLE IF NOT EXISTS` is a no-op. Every §3 column must be added in
    place, existing rows must survive, and it must be safe to run every time."""
    build_v0_store(ctx)
    before = {c["name"] for c in ctx.sql("PRAGMA table_info(wake)")}
    check(before == V0_COLUMNS, f"the v0 fixture is not v0: {sorted(before)}")

    ctx.run("stats")                                   # any verb migrates first
    after = {c["name"] for c in ctx.sql("PRAGMA table_info(wake)")}
    check(not (set(REQUIRED_COLUMNS) - after),
          f"migration left out {sorted(set(REQUIRED_COLUMNS) - after)}")

    row = ctx.row("v0-row")
    check(row["prompt"] == "old prompt" and row["created_at"] == "2026-09-18T00:00:00+00:00",
          "the migration rewrote an existing row")
    check(row["state"] == "new", f"an existing row is now {row['state']!r}")
    check(row["source"] == "manual", f"source defaulted to {row['source']!r}, not 'manual'")
    check(row["attempts"] == 0 and row["max_attempts"] == 2,
          f"attempt counters became {row['attempts']}/{row['max_attempts']}, expected 0/2")
    check(row["not_before"] is None and row["lease_until"] is None and row["cost_usd"] is None,
          "a new column came back non-null on an old row")

    ctx.run("stats")                                   # every connect, not just the first
    ctx.run("claim", "--by", "tester")                 # a migrated row is usable
    check(ctx.row("v0-row")["state"] == "claimed", "a migrated v0 row could not be claimed")
    check(ctx.row("v0-claimed")["state"] == "claimed", "the pre-existing claim was disturbed")


@guard("v0-store-migrates-and-files")
def test_v0_store_migrates_and_files(ctx: Ctx) -> None:
    """The regression that matters most: on a v0 store, `flag` must FILE. It
    used to die on `CREATE INDEX ... ON wake(source)` before the migration ran,
    and - far worse - report `suppressed:error` with exit 0, so every source on
    the authority would print `quiet` forever while the whole system looked
    green and the queue stayed empty."""
    build_v0_store(ctx)
    rel = ctx.json("flag", "--subject", "x", "--prompt", "y", "--json")
    check(rel["result"] == "filed",
          f"flag on a v0 store returned {rel['result']!r}, not 'filed' - "
          "a broken store is masquerading as a decision")
    check(rel["id"], "flag reported filed with no row id")
    check(not str(rel["result"]).startswith("error:"), f"flag errored: {rel['result']}")
    check(ctx.row("x")["prompt"] == "y", "the new row was not written")

    check(ctx.row("v0-row")["prompt"] == "old prompt", "the v0 row was rewritten")
    done = ctx.row("v0-done")
    check(done["outcome"] == "shipped it" and done["finished_at"] == "2026-09-17T01:00:00+00:00",
          "a finished v0 row lost its result - the live store holds real rows like this")
    after = {c["name"] for c in ctx.sql("PRAGMA table_info(wake)")}
    check(not (set(REQUIRED_COLUMNS) - after),
          f"v1 columns still missing: {sorted(set(REQUIRED_COLUMNS) - after)}")
    check(ctx.json("claim", "--by", "tester")["row"] is not None,
          "a freshly filed row on a migrated v0 store could not be released")


@guard("no-recursion-from-a-session")
def test_no_recursion_from_a_session(ctx: Ctx) -> None:
    """Guard 11: a woken session must not be able to raise flags, or one
    session becomes two becomes a fleet."""
    kw = dict(WAKE_SESSION=1)
    out, _ = ctx.run("flag", "--subject", "recurse", "--prompt", "p", **kw)
    check(out == "suppressed:inside-a-woken-session",
          f"flag inside a session printed {out!r}")
    check(len(ctx.sql("SELECT * FROM wake WHERE subject='recurse'")) == 0,
          "a row was filed from inside a woken session")
    rel = ctx.json("flag", "--subject", "recurse", "--prompt", "p", "--json", **kw)
    check(rel["result"] == "suppressed:inside-a-woken-session",
          f"--json reported {rel['result']!r}")
    check(rel["id"] is None, "the refusal returned a row id")

    # the explicit override has to work, or the rare deliberate case is impossible
    check(ctx.flag("recurse", allow_from_session=True, env=kw) == "filed",
          "--allow-from-session did not override the refusal")
    check(ctx.row("recurse")["state"] == "new", "the override filed a broken row")

    # and it is in the STORE layer, so any caller inherits it - not just the CLI
    probe = (
        "import importlib.util, sqlite3;"
        f"spec=importlib.util.spec_from_file_location('wake_mod', r'{WAKE_PY}');"
        "m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m);"
        "c=m.connect();"
        "print('bool', m._file_wake(c, subject='direct', prompt='p', kind='sms-await'));"
        "print('rows', c.execute(\"SELECT COUNT(*) FROM wake WHERE subject='direct'\")"
        ".fetchone()[0])"
    )
    out, _ = ctx.py(probe, **kw)
    check("bool False" in out and "rows 0" in out,
          f"the store layer did not refuse a foreign caller: {out!r}")


@guard("flag-error-is-loud")
def test_flag_error_is_loud(ctx: Ctx) -> None:
    """A broken store must never read as a quiet day. `flag` still exits 0 - it
    must not break its caller - but it reports `error:<class>: <message>` and
    NEVER `suppressed:*`, which would look like a decision."""
    blocker = ctx.tmp / "not-a-directory"
    blocker.write_text("x", encoding="utf-8")
    broken = dict(SMS_INBOX_DB=str(blocker / "inbox.db"))

    out, err = ctx.run("flag", "--subject", "broken", "--prompt", "p", **broken)
    check(out.startswith("error:"), f"a broken store printed {out!r}")
    check("suppressed" not in out, f"a broken store masqueraded as a decision: {out!r}")
    check(err.strip(), "a broken store printed nothing on stderr")

    rel = ctx.json("flag", "--subject", "broken", "--prompt", "p", "--json", **broken)
    check(rel["ok"] is False, f"a broken store reported ok={rel['ok']!r}")
    check(str(rel["result"]).startswith("error:"), f"a broken store reported {rel['result']!r}")


# --------------------------------------------------------------------------- #
def main() -> int:
    if not WAKE_PY.is_file():
        print(f"FAIL bootstrap: no wake.py at {WAKE_PY}")
        return 1
    if REAL_STORE.exists():
        print(f"note: the real store exists at {REAL_STORE} - these tests never touch it")
    before = fingerprint()
    failures = []
    for name, fn in TESTS:
        with tempfile.TemporaryDirectory(prefix="wake-guard-") as tmp:
            ctx = Ctx(tmp, {})
            try:
                fn(ctx)
            except AssertionError as exc:
                failures.append(name)
                print(f"FAIL {name}: {exc}")
            except Exception as exc:                             # noqa: BLE001
                failures.append(name)
                print(f"FAIL {name}: unexpected {type(exc).__name__}: {exc}")
            else:
                print(f"OK  {name}")
    after = fingerprint()
    if after != before:
        failures.append("real-store-untouched")
        print(f"FAIL real-store-untouched: {REAL_STORE} changed during the run "
              f"({before} -> {after})")
    if failures:
        return 1
    print("ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
