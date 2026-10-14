#!/usr/bin/env python3
"""Fixture test for ledger item 182: the PROJECT SUBJECT FAMILY key.

RUN IT
    python3 /root/bin/tests/test_wake_family_key.py
    WAKE_PY=/path/to/wake.py python3 /root/bin/tests/test_wake_family_key.py

WHAT IT PROVES
  * guard 1 (dedup), guard 2 (cooldown) and guard 9 (the attempt ceiling) are
    evaluated against the FAMILY key `project:<id>:<utc-day>` - the subject with
    a trailing `#<n>` stripped - so the `#<n>` day-suffix project-keepalive
    appends cannot step around them; and
  * a NON-project subject is byte-for-byte unchanged: `foo#2` is a subject in
    its own right and is NOT deduced against `foo`.

Every call drives the REAL CLI in a subprocess against a brand-new temp store,
and the real store's size+mtime is checked before and after the run. The temp
store is deliberate and is the estate's own convention (`test_guards.py`): a
test that can write ~/.sms-inbox/inbox.db is a test that can wake the machine
for nothing.
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

WAKE_PY = Path(os.environ.get("WAKE_PY") or "/root/bin/wake.py").resolve()
REAL_STORE = (Path.home() / ".sms-inbox" / "inbox.db").resolve()
DAY = datetime.now(timezone.utc).strftime("%Y%m%d")
FAM = f"project:probe:{DAY}"


def check(cond, why):
    if not cond:
        raise AssertionError(why)


def fingerprint():
    try:
        st = REAL_STORE.stat()
        return (True, st.st_size, st.st_mtime_ns)
    except OSError:
        return (False, 0, 0)


class Store:
    """One temp store per test, checked against the real one on every call."""

    def __init__(self, tmp):
        self.tmp = Path(tmp)
        self.db = self.tmp / "inbox.db"
        self.pause = self.tmp / "WAKE_PAUSED"

    def env(self, **kw):
        env = {k: v for k, v in os.environ.items() if not k.startswith("WAKE_")}
        env["SMS_INBOX_DB"] = str(self.db)
        env["WAKE_PAUSE_FILE"] = str(self.pause)
        env["PYTHONIOENCODING"] = "utf-8"
        env.update({k: str(v) for k, v in kw.items()})
        got = Path(env["SMS_INBOX_DB"]).resolve()
        check(got != REAL_STORE, f"test store {got} IS the real store {REAL_STORE}")
        check(str(self.tmp) in str(got), f"test store {got} is outside {self.tmp}")
        return env

    def run(self, *args, **kw):
        argv = [str(a) for a in args]
        proc = subprocess.run([sys.executable, str(WAKE_PY), *argv], env=self.env(**kw),
                              capture_output=True, text=True, cwd=str(self.tmp))
        check(proc.returncode == 0,
              f"`{' '.join(argv)}` exited {proc.returncode}: {proc.stderr.strip()[:200]}")
        return proc.stdout.strip(), proc.stderr.strip()

    def flag(self, subject, *, prompt="do the thing", **kw):
        env = {k: v for k, v in kw.items() if k.startswith("WAKE_")}
        opts = {k: v for k, v in kw.items() if not k.startswith("WAKE_")}
        args = ["flag", "--subject", subject, "--prompt", prompt]
        for key, val in opts.items():
            args += ["--" + key.replace("_", "-"), str(val)]
        out, err = self.run(*args, **env)
        return out, err

    def json(self, *args, **kw):
        out, _ = self.run(*args, "--json", **kw)
        return json.loads(out)

    def sql(self, query):
        conn = sqlite3.connect(str(self.db), timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            return [dict(r) for r in conn.execute(query).fetchall()]
        finally:
            conn.close()

    def id_of(self, subject):
        rows = self.sql("SELECT id FROM wake WHERE subject=%s" % _q(subject))
        check(rows, f"no row for {subject!r}")
        return rows[0]["id"]


def _q(text: str) -> str:
    return "'" + str(text).replace("'", "''") + "'"


def test_family_dedup():
    """Guard 1 against the family: a live base subject dedups `#2` and `#3`."""
    with tempfile.TemporaryDirectory(prefix="wake-fam-") as tmp:
        s = Store(tmp)
        out, _ = s.flag(FAM)
        check(out == "filed", f"the family's first flag printed {out!r}, not filed")
        out, _ = s.flag(FAM + "#2")
        check(out == "deduped", f"a live family member did not dedup #2: {out!r}")
        out, _ = s.flag(FAM + "#3", source="project-keepalive")
        check(out == "deduped", f"the #3 flag was not deduped: {out!r}")
        rows = s.sql("SELECT subject FROM wake WHERE subject LIKE %s" % _q(FAM + "%"))
        check(len(rows) == 1, f"{len(rows)} family rows after three flags; expected 1: {rows}")


def test_family_cooldown():
    """Guard 2 against the family: once the family has been RELEASED, flagging
    `#2` inside the cooldown must be suppressed - and the suppression must NAME
    the family release it is inside of. (While the release is still live, guard 1
    dedups first; that is `family-dedup`.)"""
    with tempfile.TemporaryDirectory(prefix="wake-fam-") as tmp:
        s = Store(tmp)
        out, _ = s.flag(FAM)
        check(out == "filed", f"the family's first flag printed {out!r}, not filed")
        rel = s.json("claim", "--by", "tester")
        check(rel["row"] is not None and rel["row"]["subject"] == FAM,
              f"the family was not released: {rel.get('row')}")
        s.run("finish", str(s.id_of(FAM)), "--outcome", "done")
        out, err = s.run("flag", "--subject", FAM + "#2", "--prompt", "p", "--json")
        d = json.loads(out)
        check(d["result"] == "suppressed:cooldown",
              f"the #2 flag printed {d['result']!r}, not suppressed:cooldown")
        det = d.get("detail") or {}
        check(det.get("family") == FAM, f"the suppression does not name the family: {det}")
        check(det.get("family_row"), f"the suppression does not name the family release row: {det}")
        check("cooldown" in (det.get("note") or ""),
              f"the note does not name the release: {det.get('note')!r}")
        check(str(det.get("family_row")) in err,
              f"stderr does not name the family release it is inside of: {err!r}")
        rows = s.sql("SELECT subject FROM wake WHERE subject=%s" % _q(FAM + "#2"))
        check(not rows, "the cooldown-suppressed flag still wrote a #2 row")


def test_family_attempts():
    """Guard 9 against the family: the family's attempt ledger carries, so the
    day-suffix cannot multiply the attempt ceiling."""
    with tempfile.TemporaryDirectory(prefix="wake-fam-") as tmp:
        s = Store(tmp)
        kw = dict(WAKE_COOLDOWN_SEC=0, WAKE_MAX_PER_SOURCE_PER_HOUR=50)
        out, _ = s.flag(FAM, **kw)
        check(out == "filed", f"the first flag printed {out!r}")
        rel = s.json("claim", "--by", "tester", **kw)
        check(rel["row"] is not None and rel["row"]["subject"] == FAM,
              f"the first family release was not the base subject: {rel.get('row')}")
        s.run("finish", str(s.id_of(FAM)), "--failed", "--outcome", "no good", **kw)

        out, _ = s.flag(FAM + "#2", **kw)
        check(out == "filed", f"a failed family member with attempts left did not allow #2: {out!r}")
        row2 = s.sql("SELECT attempts FROM wake WHERE subject=%s" % _q(FAM + "#2"))
        check(row2 and row2[0]["attempts"] == 1,
              f"#2 did not carry the family's attempt ledger: {row2}")
        rel = s.json("claim", "--by", "tester", **kw)
        check(rel["row"] is not None and rel["row"]["subject"] == FAM + "#2",
              f"the #2 release did not happen: {rel.get('row')}")
        s.run("finish", str(s.id_of(FAM + "#2")), "--failed", "--outcome", "no good", **kw)

        out, _ = s.flag(FAM + "#3", **kw)
        check(out == "suppressed:attempts",
              f"the family was retried past its attempt ceiling: {out!r}")


def test_non_project_unchanged():
    """A non-project subject has no family: `foo#2` is its own subject."""
    with tempfile.TemporaryDirectory(prefix="wake-fam-") as tmp:
        s = Store(tmp)
        out, _ = s.flag("plain")
        check(out == "filed", f"plain did not file: {out!r}")
        out, _ = s.flag("plain#2")
        check(out == "filed",
              f"a NON-project `#2` was collapsed into a family (printed {out!r})")
        rows = s.sql("SELECT subject FROM wake WHERE subject LIKE 'plain%%'")
        check(len(rows) == 2,
              f"{len(rows)} rows for plain/plain#2 - a non-project subject must be unchanged: {rows}")
        out, _ = s.flag("plain")
        check(out == "deduped", f"re-flagging the still-live plain printed {out!r}")
        # and the boundary really is the project:<id>:<8-digit-day> shape
        out, _ = s.flag("project:x:20261#2")
        check(out == "filed",
              f"a subject that only LOOKS project-shaped was collapsed: {out!r}")


TESTS = [
    ("family-dedup", test_family_dedup),
    ("family-cooldown", test_family_cooldown),
    ("family-attempts", test_family_attempts),
    ("non-project-unchanged", test_non_project_unchanged),
]


def main() -> int:
    if not WAKE_PY.is_file():
        print(f"FAIL bootstrap: no wake.py at {WAKE_PY}")
        return 1
    if REAL_STORE.exists():
        print(f"note: the real store exists at {REAL_STORE} - these tests never touch it")
    before = fingerprint()
    failures = []
    for name, fn in TESTS:
        try:
            fn()
        except AssertionError as exc:
            failures.append(name)
            print(f"FAIL {name}: {exc}")
        except Exception as exc:                                  # noqa: BLE001
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
