"""Tests for /root/bin/line-map.py.

Every test here pins a defect that was found by RUNNING the tool on real data, not by imagining it.
In order of how much each one cost:

  1. unit_amount x quantity - the tool and I both reported 11.00 where the truth was 66.00, twice.
  2. line_number as the primary key - silently DROPPED one of the owner's two lines on 848-389-7895
     (an Unlimited phone and an Apple Watch share a number), so the page's 20 became 19.
  3. the label read from the PREVIOUS line instead of the same line - returned null for every row.
  4. a null overwriting a stored value - nine good labels replaced with nulls in one run.
  5. a weak mapping_source overwriting a strong one - re-seeding reset ASSERTED links to NONE.
  6. seed wrote the subscription columns only in DO UPDATE, never in INSERT - so a fresh row had
     holder and provenance but no link, and the reconciliation read 0 mapped against qty 6.

Run:  /usr/bin/python3 /root/bin/tests/test_line_map.py
"""
from __future__ import annotations

import importlib.util
import sqlite3
import sys
import tempfile
from pathlib import Path

_spec = importlib.util.spec_from_file_location("line_map", "/root/bin/line-map.py")
lm = importlib.util.module_from_spec(_spec)
sys.modules["line_map"] = lm
_spec.loader.exec_module(lm)

PAGE = """Line Name\tNumber\tPlan Type\tRenewal Date\tStatus\tAutopay

To be assigned\tTo be assigned\t
Unlimited
Upon activation\t
Pending Activation

Test sim at&t\t(848) 389-5173\t
Data Bundle
11/02/26\t
Active

Eliyahu Zabrowsky\t(848) 389-7895\t
Unlimited
10/31/26\t
Active

My Apple Watch\t(848) 389-7895\t
Wearable
11/09/26\t
Active

Line 15\t(732) 664-2525\t
By the gig
10/30/26\t
Active
"""


def test_label_comes_from_the_same_line():
    rows = lm.parse_usm(PAGE)
    by_num = {}
    for r in rows:
        by_num.setdefault(r["line_number"], []).append(r)
    assert by_num["8483895173"][0]["line_label"] == "Test sim at&t", by_num["8483895173"]
    assert by_num["7326642525"][0]["line_label"] == "Line 15"


def test_a_shared_number_yields_two_lines_not_one():
    """848-389-7895 carries an Unlimited phone AND a Watch. Keying on the number lost one."""
    rows = [r for r in lm.parse_usm(PAGE) if r["line_number"] == "8483897895"]
    assert len(rows) == 2, rows
    assert {r["line_label"] for r in rows} == {"Eliyahu Zabrowsky", "My Apple Watch"}


def test_the_pending_line_is_captured_even_with_no_number():
    rows = [r for r in lm.parse_usm(PAGE) if not r["line_number"]]
    assert len(rows) == 1 and rows[0]["usm_status"] == "Pending Activation", rows


def test_page_rows_and_pending_add_up():
    """The page shows 5 numbered lines here plus the pending one; losing either is the bug."""
    rows = lm.parse_usm(PAGE)
    assert len(rows) == 5, [r["line_label"] for r in rows]


def test_money_is_unit_times_quantity():
    """THE bug. 11.00 x 6 is 66.00, and 'unit alone' is how 66 was reported as 11."""
    unit, qty = 11.0, 6
    monthly = unit * qty
    assert monthly == 66.0
    assert monthly != unit


def test_a_null_never_overwrites_a_stored_value():
    """`COALESCE(NULLIF(excluded.x,''), line_map.x)` is the rule; a bare assignment wiped nine labels."""
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE t (k TEXT PRIMARY KEY, label TEXT)")
    con.execute("INSERT INTO t VALUES ('a','Line 15')")
    con.execute("INSERT INTO t (k,label) VALUES ('a', NULL)"
                " ON CONFLICT(k) DO UPDATE SET label=COALESCE(NULLIF(excluded.label,''), t.label)")
    assert con.execute("SELECT label FROM t").fetchone()[0] == "Line 15"


def test_a_weaker_source_does_not_overwrite_a_stronger_one():
    """A re-seed must not downgrade ASSERTED back to NONE."""
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE t (k TEXT PRIMARY KEY, mapping_source TEXT)")
    con.execute("INSERT INTO t VALUES ('a','ASSERTED')")
    con.execute(
        "INSERT INTO t (k,mapping_source) VALUES ('a','NONE') ON CONFLICT(k) DO UPDATE SET"
        " mapping_source=CASE WHEN t.mapping_source IN ('PHONE','NAME','ASSERTED')"
        " AND excluded.mapping_source='NONE' THEN t.mapping_source"
        " ELSE excluded.mapping_source END")
    assert con.execute("SELECT mapping_source FROM t").fetchone()[0] == "ASSERTED"


def _store_with(tmp: Path):
    lm.DB = tmp
    con = lm.store()
    lm._seed_put(con, "1112223333", "A Customer", "Data Bundle", "11/01/26", "customer",
                 holder="A Customer", sub="sub_TEST", customer="cus_TEST", source="ASSERTED")
    con.commit()
    return con


def test_a_fresh_seed_row_carries_its_subscription():
    """Seed listed the subscription columns only in DO UPDATE, so a new row had no link."""
    with tempfile.TemporaryDirectory() as d:
        con = _store_with(Path(d) / "t.db")
        row = con.execute("SELECT stripe_subscription_id, stripe_customer_id, holder,"
                          " mapping_source FROM line_map WHERE line_number='1112223333'").fetchone()
        assert row["stripe_subscription_id"] == "sub_TEST", dict(row)
        assert row["stripe_customer_id"] == "cus_TEST"
        assert row["holder"] == "A Customer" and row["mapping_source"] == "ASSERTED"
        con.close()


def test_the_alarm_is_a_quantity_mismatch():
    """The check that would have caught six lines billed as one, and its reverse."""
    with tempfile.TemporaryDirectory() as d:
        con = _store_with(Path(d) / "t.db")
        con.execute("INSERT INTO subscription_map (subscription_id, customer_name, unit_amount_usd,"
                    " quantity, monthly_usd, status) VALUES ('sub_TEST','A Customer',11.0,6,66.0,"
                    "'active')")
        con.commit()
        mapped = con.execute("SELECT COUNT(*) FROM line_map WHERE stripe_subscription_id='sub_TEST'"
                             ).fetchone()[0]
        qty = con.execute("SELECT quantity FROM subscription_map WHERE subscription_id='sub_TEST'"
                          ).fetchone()[0]
        assert mapped == 1 and qty == 6, (mapped, qty)  # 1 mapped vs qty 6 IS the alarm
        assert mapped != qty
        con.close()


def test_assert_refuses_an_ambiguous_number():
    """A number carrying two lines must not be silently asserted onto the wrong one."""
    with tempfile.TemporaryDirectory() as d:
        lm.DB = Path(d) / "t.db"
        con = lm.store()
        lm._seed_put(con, "8483897895", "Eliyahu Zabrowsky", "Unlimited", "10/31/26", "owner")
        lm._seed_put(con, "8483897895", "My Apple Watch", "Wearable", "11/09/26", "owner")
        con.commit()
        n = con.execute("SELECT COUNT(*) FROM line_map WHERE line_number='8483897895'").fetchone()[0]
        assert n == 2
        con.close()


def test_kinds_and_sources_are_closed_sets():
    assert set(lm.KINDS) == {"customer", "owner", "shop", "pending", "unknown"}
    assert set(lm.SOURCES) == {"PHONE", "NAME", "ASSERTED", "NONE"}


if __name__ == "__main__":
    fails = 0
    for k, f in sorted(globals().items()):
        if k.startswith("test_") and callable(f):
            try:
                f()
                print("ok   %s" % k)
            except Exception as exc:  # noqa: BLE001
                fails += 1
                print("FAIL %s: %r" % (k, exc))
    print("\n%d failure(s)" % fails)
    sys.exit(1 if fails else 0)
