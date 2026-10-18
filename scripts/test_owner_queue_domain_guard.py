#!/usr/bin/env python3
"""Tests for the owner-queue domain guard (owner instruction, 2026-10-18).

Run against the deployed tool:

    OWNER_QUEUE_TOOL=/root/bin/owner-queue.py \
      python3 scripts/test_owner_queue_domain_guard.py -v

or, from the repo, against its sibling `owner-queue.py` with no env var. Every test
uses a throwaway database under a temporary directory; nothing here touches
/root/authority.db or /root/work/work.db.
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOL = Path(os.environ.get("OWNER_QUEUE_TOOL")
            or Path(__file__).with_name("owner-queue.py"))


class DomainGuardTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="owner-queue-domain-")
        self.db = os.path.join(self.tmp.name, "queue.db")

    def tearDown(self):
        self.tmp.cleanup()

    def run_tool(self, *args, timeout=90):
        cmd = [sys.executable, str(TOOL), "--db", self.db] + list(args)
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)

    def count(self):
        con = sqlite3.connect(self.db)
        try:
            return con.execute(
                "SELECT COUNT(*) FROM owner_decision_queue").fetchone()[0]
        finally:
            con.close()

    # 1 ─ a customer-shaped row is refused, with the rule and the alternative.
    def test_customer_shaped_row_is_refused_with_actionable_message(self):
        r = self.run_tool(
            "add", "--question",
            "Customer left a voicemail about WO26-0417; what should we tell them?")
        self.assertEqual(r.returncode, 5, r.stdout + r.stderr)
        self.assertIn("OWNER-QUEUE DOMAIN RULE", r.stdout)
        self.assertIn("customer/business work belongs in the ledger", r.stdout)
        self.assertIn("work.py add --project", r.stdout)
        self.assertIn("lpt-sync", r.stdout)
        self.assertIn("--owner-worthy --owner-reason", r.stdout)
        self.assertIn("Nothing was written", r.stdout)
        self.assertEqual(self.count(), 0)

    # 2 ─ an owner-shaped row still files, with no marker needed.
    def test_owner_shaped_row_still_files(self):
        r = self.run_tool(
            "add", "--question",
            "Should the shop match the competitor's $49 screen-protector price?")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("queued #", r.stdout)
        self.assertEqual(self.count(), 1)

    # 2b ─ "waiting on your decision" is an owner row, not a customer one.
    def test_owner_directed_waiting_is_not_a_keyword_hit(self):
        r = self.run_tool(
            "add", "--question",
            "We are waiting on your approval for the new label printer budget.")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("queued #", r.stdout)
        self.assertEqual(self.count(), 1)

    # 3 ─ the explicit marker works even when there is no keyword at all.
    def test_explicit_customer_domain_is_refused(self):
        r = self.run_tool(
            "add", "--domain", "customer", "--question",
            "Should we buy a new bench lamp for the back room?")
        self.assertEqual(r.returncode, 5, r.stdout + r.stderr)
        self.assertIn("filed as: --domain customer", r.stdout)
        self.assertIn("Nothing was written", r.stdout)
        self.assertEqual(self.count(), 0)

    # 4 ─ the escape is refused without a reason ...
    def test_escape_without_reason_is_refused(self):
        r = self.run_tool(
            "add", "--owner-worthy", "--question",
            "Customer asked for a refund after a repair; do you approve?")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("requires a non-empty --owner-reason", r.stdout)
        self.assertIn("Nothing was written", r.stdout)
        self.assertEqual(self.count(), 0)

    # ... and works with one.
    def test_escape_with_reason_files(self):
        r = self.run_tool(
            "add", "--owner-worthy",
            "--owner-reason",
            "Refund policy is a legal posture decision only the owner can set.",
            "--question",
            "Customer asked for a refund after a repair; do you approve?")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("owner-worthy escape", r.stdout)
        self.assertIn("queued #", r.stdout)
        self.assertEqual(self.count(), 1)

    # 4b ─ the JSON path carries the same marker and escape.
    def test_from_json_domain_is_refused(self):
        payload = {"question": "Should we buy a bench lamp for the back room?",
                   "domain": "customer"}
        path = os.path.join(self.tmp.name, "row.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
        r = self.run_tool("add", "--from-json", path)
        self.assertEqual(r.returncode, 5, r.stdout + r.stderr)
        self.assertIn("filed as: --domain customer", r.stdout)
        self.assertEqual(self.count(), 0)

    def test_from_json_escape_with_reason_files(self):
        payload = {"question": "Customer asked for a refund; do you approve?",
                   "domain": "customer", "owner_worthy": True,
                   "owner_reason": "Refund policy is a legal posture decision."}
        path = os.path.join(self.tmp.name, "row.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
        r = self.run_tool("add", "--from-json", path)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("owner-worthy escape", r.stdout)
        self.assertEqual(self.count(), 1)

    # 5 ─ the sweep finds a row planted in a database that predates the guard.
    def test_sweep_finds_a_planted_row_and_changes_nothing(self):
        r = self.run_tool(
            "add", "--question", "Should we keep the Saturday closing time?")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

        con = sqlite3.connect(self.db)
        try:
            con.execute(
                "INSERT INTO owner_decision_queue "
                "(asked_at, question, context, recommendation, severity, status) "
                "VALUES (?,?,?,?,?, 'pending')",
                ("2026-10-18T01:00:00+00:00",
                 "Customer is waiting for a callback about WO26-9999",
                 "Customer called twice.", "Call them back.", "high"))
            con.commit()
            planted = con.execute(
                "SELECT id FROM owner_decision_queue WHERE question LIKE 'Customer is%'"
            ).fetchone()[0]
        finally:
            con.close()
        before = self.count()

        r = self.run_tool("sweep")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("would be refused", r.stdout)
        self.assertIn(f"#{planted}", r.stdout)
        self.assertIn("READ-ONLY", r.stdout)
        self.assertEqual(self.count(), before, "sweep must not delete or move rows")

        j = self.run_tool("sweep", "--json")
        self.assertEqual(j.returncode, 1, j.stdout + j.stderr)
        payload = json.loads(j.stdout)
        self.assertEqual(payload["would_refuse"], 1)
        self.assertEqual(payload["rows"][0]["id"], planted)
        self.assertIn("customer", json.dumps(payload["rows"][0]["hits"]))

    # 6 ─ a clean queue is a real zero.
    def test_sweep_reports_a_clean_queue(self):
        r = self.run_tool(
            "add", "--question", "Should we renew the workshop insurance in March?")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        s = self.run_tool("sweep")
        self.assertEqual(s.returncode, 0, s.stdout + s.stderr)
        self.assertIn("0 would be refused", s.stdout)
        self.assertIn("scanned", s.stdout)

    # 7 ─ the old commands still behave on a normal row.
    def test_stats_next_list_and_amend_still_work(self):
        r = self.run_tool(
            "add", "--question", "Should we renew the workshop insurance in March?")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

        stats = self.run_tool("stats")
        self.assertEqual(stats.returncode, 0, stats.stdout + stats.stderr)
        self.assertIn("pending: 1", stats.stdout)

        nxt = self.run_tool("next", "--peek", "2")
        self.assertEqual(nxt.returncode, 0, nxt.stdout + nxt.stderr)
        self.assertIn("#1", nxt.stdout)

        listing = self.run_tool("list")
        self.assertEqual(listing.returncode, 0, listing.stdout + listing.stderr)
        self.assertIn("#1", listing.stdout)

        amend = self.run_tool("amend", "1", "--note", "test amendment",
                              "--context", "Updated context for the test.")
        self.assertEqual(amend.returncode, 0, amend.stdout + amend.stderr)
        self.assertIn("#1 amended", amend.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
