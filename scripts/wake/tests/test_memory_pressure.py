#!/usr/bin/env python3
"""Unit tests for the memory-pressure wake source (ledger item 685).

RUN IT
    python3 scripts/wake/tests/test_memory_pressure.py

WHAT IT PROVES
  * a cache-heavy service whose MemoryCurrent is above 60 percent but whose
    anon+shmem is below 60 percent produces NO memory-high finding;
  * an anon-high service does produce one;
  * an OOM kill older than the current ExecMainStartTimestamp is not re-flagged
    when the day's subject has already been alerted, while an unalerted old kill
    and a post-restart kill are still reported;
  * the real wake-store lookup used by the covered-kill rule reads a temp store,
    never ~/.sms-inbox/inbox.db.
"""
from __future__ import annotations

import importlib.util
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
SOURCES = HERE.parent / "sources"
sys.path.insert(0, str(SOURCES))

spec = importlib.util.spec_from_file_location(
    "memory_pressure_source", SOURCES / "memory-pressure.py"
)
mp = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(mp)

CAP = 12_884_901_888
KILL_TS = datetime(2026, 10, 19, 7, 20, 22, tzinfo=timezone.utc)
START_TS = datetime(2026, 10, 19, 8, 14, 0, tzinfo=timezone.utc)


def _findings(*, current: int, anon: int, kills, start, alerted: bool):
    with patch.object(mp._flag, "unit_exists", return_value=True), \
         patch.object(mp, "_show", side_effect=lambda prop: {
             "MemoryCurrent": str(current),
             "MemoryMax": str(CAP),
         }[prop]), \
         patch.object(mp, "_exec_main_start", return_value=start), \
         patch.object(mp, "_memory_stat", return_value={"anon": anon, "shmem": 0, "file": 1}), \
         patch.object(mp, "_oom_kills", return_value=kills), \
         patch.object(mp, "_swap", return_value=(8_000_000, 8_000_000)), \
         patch.object(mp, "_already_alerted", return_value=alerted):
        return mp.collect(None)


class MemoryPressureTests(unittest.TestCase):
    def test_cache_heavy_anon_low_has_no_memory_high(self):
        # MemoryCurrent is 68.8% of the cap; anon+shmem is only 11.6%. The old
        # source would have filed memory-high here. This one must be quiet.
        found = _findings(current=8_869_793_792, anon=1_500_000_000, kills=[],
                          start=START_TS, alerted=False)
        self.assertEqual(found, [], [f.subject for f in found])

    def test_anon_high_files_memory_high(self):
        # 8.0 GB of non-reclaimable memory is 62.1% of the cap.
        found = _findings(current=8_869_793_792, anon=8_000_000_000, kills=[],
                          start=START_TS, alerted=False)
        self.assertEqual([f.subject for f in found], ["memory-high:60"])

    def test_kill_before_restart_already_alerted_is_not_refired(self):
        found = _findings(current=4_000_000_000, anon=1_000_000_000,
                          kills=[(KILL_TS, "Oct 19 07:20:22 ... Failed with result 'oom-kill'")],
                          start=START_TS, alerted=True)
        self.assertEqual(found, [], [f.subject for f in found])

    def test_kill_before_restart_unalerted_still_files_once(self):
        found = _findings(current=4_000_000_000, anon=1_000_000_000,
                          kills=[(KILL_TS, "Oct 19 07:20:22 ... Failed with result 'oom-kill'")],
                          start=START_TS, alerted=False)
        self.assertEqual([f.subject for f in found], ["memory-oom:20261019"])

    def test_kill_after_restart_files_even_when_day_was_alerted(self):
        kill = START_TS + timedelta(hours=1)
        found = _findings(current=4_000_000_000, anon=1_000_000_000,
                          kills=[(kill, "Oct 19 09:14:00 ... Failed with result 'oom-kill'")],
                          start=START_TS, alerted=True)
        self.assertEqual([f.subject for f in found], ["memory-oom:20261019"])

    def test_journal_status_banner_is_not_a_kill(self):
        # The repo's _flag.py predates the live journal-status filter. A clean
        # window returns `-- No entries --`; treating it as a kill would file an
        # OOM finding for an outage that did not happen.
        with patch.object(mp._flag, "journal_grep", return_value=["-- No entries --"]):
            self.assertEqual(mp._oom_kills(2), [])

    def test_exec_main_start_parses_systemd_timestamp(self):
        with patch.object(mp, "_show", return_value="Mon 2026-10-19 08:14:00 UTC"):
            self.assertEqual(mp._exec_main_start(), START_TS)

    def test_exec_main_start_is_none_when_stopped(self):
        with patch.object(mp, "_show", return_value="n/a"):
            self.assertIsNone(mp._exec_main_start())

    def test_already_alerted_reads_the_wake_store(self):
        with tempfile.TemporaryDirectory(prefix="mem-pressure-") as tmp:
            db = Path(tmp) / "inbox.db"
            conn = sqlite3.connect(str(db))
            try:
                conn.execute("CREATE TABLE wake (subject TEXT NOT NULL)")
                conn.execute("INSERT INTO wake (subject) VALUES (?)",
                             ("memory-oom:20261019",))
                conn.commit()
            finally:
                conn.close()
            with patch.object(mp._flag, "inbox_db", return_value=db):
                self.assertTrue(mp._already_alerted("memory-oom:20261019"))
                self.assertFalse(mp._already_alerted("memory-oom:20261018"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
