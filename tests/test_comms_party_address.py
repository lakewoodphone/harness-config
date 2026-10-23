"""Pins the party address used for the AI line's own sms_log/call_log rows.

LEDGER ITEM 1195. The indexer took `from_number` first, so every OUTBOUND row from
the shop's Twilio AI line was keyed to +17324447361 (ourselves). `ps_comms_waiting`
compares the last inbound party with an outbound on the same party_key, so after the
owner's reply was delivered (sms_log 4407, SID SMb25e298981f15252c8b0db842e042f1f)
he stayed on the waiting list: the reply was filed under the shop, not under him.

The rule: the address is the OTHER party. Inbound -> from_number, outbound ->
to_number. The test covers both directions, both source tables, and the fallback.

Run:
  COMMS_INDEX=/root/_hk1195_wt/scripts/commsindex.py \
      python3 tests/test_comms_party_address.py
"""
import importlib.util
import os
import sqlite3
import sys

ENGINE = os.environ.get("COMMS_INDEX", "/root/.fsearch/commsindex.py")

spec = importlib.util.spec_from_file_location("commsindex", ENGINE)
ci = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ci)

SHOP = "+17324447361"      # the Twilio AI line
CUSTOMER = "+18483897895"  # the owner in item 1195


def _con():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("""CREATE TABLE sms_log (
        id INTEGER PRIMARY KEY, twilio_sid TEXT,
        direction TEXT NOT NULL DEFAULT 'outbound',
        from_number TEXT NOT NULL, to_number TEXT NOT NULL,
        body TEXT NOT NULL, template_id TEXT,
        status TEXT NOT NULL DEFAULT 'queued', error_message TEXT,
        agent_id TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
    con.execute("""CREATE TABLE call_log (
        id INTEGER PRIMARY KEY, direction TEXT, from_number TEXT, to_number TEXT,
        contact_name TEXT, notes TEXT, summary TEXT, duration_seconds INTEGER,
        created_at TEXT)""")
    ts = "2026-10-23T14:55:27+00:00"
    con.execute("INSERT INTO sms_log(id,direction,from_number,to_number,body,"
                "status,created_at,updated_at) VALUES"
                "(1,'inbound',?,?, 'question','received',?,?)",
                (CUSTOMER, SHOP, ts, ts))
    con.execute("INSERT INTO sms_log(id,direction,from_number,to_number,body,"
                "status,created_at,updated_at) VALUES"
                "(2,'outbound',?,?, 'answer','delivered',?,?)",
                (SHOP, CUSTOMER, ts, ts))
    # One empty side: still addressable as the far party.
    con.execute("INSERT INTO sms_log(id,direction,from_number,to_number,body,"
                "status,created_at,updated_at) VALUES"
                "(3,'outbound',?,'', 'fallback','delivered',?,?)",
                (SHOP, ts, ts))
    con.execute("INSERT INTO call_log(id,direction,from_number,to_number,"
                "contact_name,notes,created_at) VALUES"
                "(1,'inbound',?,?, 'owner','inbound call',?)",
                (CUSTOMER, SHOP, ts))
    con.execute("INSERT INTO call_log(id,direction,from_number,to_number,"
                "contact_name,notes,created_at) VALUES"
                "(2,'outbound',?,?, 'owner','outbound call',?)",
                (SHOP, CUSTOMER, ts))
    return con


def main() -> int:
    con = _con()
    sms = {r["ref"]: r for r in ci.rows_sms_log(con)}
    calls = {r["ref"]: r for r in ci.rows_call_log(con)}
    failures = []
    for ref, want in (("sl:1", CUSTOMER), ("sl:2", CUSTOMER), ("sl:3", SHOP)):
        got = sms[ref]["address"]
        print(f"{ref}: direction={sms[ref]['direction']:<8} address={got}")
        if got != want:
            failures.append(f"{ref}: want {want}, got {got}")
    for ref, want in (("cl:1", CUSTOMER), ("cl:2", CUSTOMER)):
        got = calls[ref]["address"]
        print(f"{ref}: direction={calls[ref]['direction']:<8} address={got}")
        if got != want:
            failures.append(f"{ref}: want {want}, got {got}")
    if failures:
        print("FAIL: " + "; ".join(failures), file=sys.stderr)
        return 1
    print("PASS: outbound replies are keyed to the recipient, not the shop line")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
