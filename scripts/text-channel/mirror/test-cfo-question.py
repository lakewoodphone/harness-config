#!/usr/bin/env python3
"""test-cfo-question.py — the four defects in the owner's charge questions, asserted.

PURE FUNCTIONS AND NOTHING ELSE. No network, no live API, no ledger, no ~/.cfo-asks,
no authority database, no tempfile either -- the two seams under test (`charge_msg.
build_body()` and `cfo-ask.ask_suppression()`) take every input as an argument, so
neither needs a store to be exercised. `charge_msg.build_body()` deliberately does no
lookup of its own, which is why the body the owner would read can be asserted here
without touching a mailbox.

    python test-cfo-question.py          # exits 0 when every check passes

The four defects, in the owner's words:
  1. "why do you even have to ask me" (2026-10-02)      -- the shop-supplies guess
  2. "exhaust all of the resources ... then give me all the details you found" (10-16)
  3. "mixing a CFO question and part of an email and ... what's the plus one more"
  4. one answer about a shop suppressed every future charge there
"""
from __future__ import annotations

import importlib.util
import inspect
import os
import re
import shutil
import sqlite3
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

# EVERY STORE THAT COULD BE REACHED IS POINTED AT A TEMP DIRECTORY BEFORE `cfo-ask.py` IS
# IMPORTED, because its paths are read at import time and this is the only moment that can
# do it. No real ledger, no ~/.cfo-asks, no authority database and no mailbox is touched:
# the only database this file opens is the one it creates itself, for one test.
TMP = Path(tempfile.mkdtemp(prefix="cfo-question-test-"))
os.environ.update({
    "CFO_ACCT_DB": str(TMP / "accounting.db"),
    "CFO_ASK_DB": str(TMP / "asks.db"),
    "OWNER_ASK_DB": str(TMP / "owner-ask.db"),
    "SECRETARY_DB": str(TMP / "no-mailbox.db"),
    # The caps are a policy, not the thing under test: the gap floor would otherwise hide
    # the second question this file proves is askable.
    "CFO_ASK_MIN_GAP_MINUTES": "0",
    "CFO_ASK_MAX_PER_DAY": "99",
})
os.environ.pop("CFO_ASK_INCLUDE_PARKED", None)

import charge_msg as cm                                    # noqa: E402

FAILURES: list = []


def check(name: str, ok, detail: str = "") -> None:
    if ok:
        print("ok   %s" % name)
    else:
        print("FAIL %s%s" % (name, ("  <- " + detail) if detail else ""))
        FAILURES.append(name)


def load_cfo_ask():
    """`cfo-ask.py` has a hyphen in its name, so it cannot be imported by name."""
    spec = importlib.util.spec_from_file_location("cfo_ask_under_test", HERE / "cfo-ask.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


cfo = load_cfo_ask()

AMOUNT_RE = re.compile(r"(?:^|[\s(])\$?\s*\d{1,3}(?:,\d{3})*\.\d{2}|\d+\.\d{2}\b")

# ── the bodies this file renders, for the blanket assertions ────────────────
DEEPSEEK_MERCHANT = "hangzhou-deepseek-artificial-intelligence-co.,-ltd"
CHECKED_FUEL = ["records:ledger: nothing for fuel", "aliases: no alias",
                "records:owner-answer: never asked"]

#: What he was ACTUALLY sent on 2026-10-05 02:00 and called confusing: a CFO question,
#: a fragment of an email subject, "a +1 more" and a second merchant.
MESSY = (
    "CFO [ask-1792026036]: 135.33 at pass on 5 Oct, card ending 9650.\n"
    "Email: 2026-10-05 (+1 more) chase.com - Your receipt for the order you placed\n"
    "Also this merchant: 12.00 on 3 Oct, 9.99 on 1 Oct.\n"
    "3 charges, 157.32 total.\n"
    "No guess from me - what was it? One line and I'll file it for good."
)

#: The 2026-10-02 body that opened this whole complaint.
LEGACY_GUESS = (
    "CFO: 53.00 at " + DEEPSEEK_MERCHANT + " on 2 Oct, card ending 2205.\n"
    "My guess: shop supplies. Reply 'yes' - or tell me what it was and I'll file it for good."
)


def rendered_bodies() -> list:
    return [
        cm.build_body(5795, "Fuel", "28 Aug", "9650", checked=CHECKED_FUEL),
        cm.build_body(5300, DEEPSEEK_MERCHANT, "2 Oct", "2205",
                      checked=["descriptor: matched 'deepseek' -> Software & Online Services (conf 0.80)"],
                      category="Software & Online Services", category_source="descriptor"),
        cm.build_body(36251, "new egg", "13 Oct", "9650",
                      checked=["orders: not_found", "receipts: not_found"],
                      order_lines=["order #419077624 - Dell Latitude 7430"]),
        cm.build_body(3200, "polka dot", "9 Oct", "2005"),                  # nothing checked
        cm.build_body(13533, "pass", "5 Oct", "9650",
                      checked=["descriptor: matched pass"], category="Parking & Tolls",
                      category_source="descriptor"),
        cm.enforce_one_charge(MESSY),
        cm.enforce_one_charge(LEGACY_GUESS),
        cm.render("CFO: 12.00 at " + ("Alpha " * 40) + "on 1 Jan, card ending 1234.",
                  ask=cm.DEFAULT_ASK, limit=120),
    ]


# ── 1. THE GUESS ────────────────────────────────────────────────────────────
def test_no_guess():
    for i, body in enumerate(rendered_bodies(), 1):
        low = body.lower()
        check("guess: body %d carries no 'my guess'" % i, "my guess" not in low, body)
        check("guess: body %d never says 'shop supplies'" % i, "shop supplies" not in low, body)
        check("guess: body %d offers no guessing at all" % i, "guess" not in low, body)

    # The legacy body IS the guess. It must come out without it, and without the
    # "Reply 'yes' - or tell me what it was" that the guess invited him to answer.
    fixed = cm.enforce_one_charge(LEGACY_GUESS)
    check("guess: the legacy body is cleaned", "shop supplies" not in fixed.lower(), fixed)
    check("guess: the legacy body no longer invites a yes", "reply" not in fixed.lower(), fixed)
    check("guess: the legacy body no longer asks what it was",
          "what was it" not in fixed.lower(), fixed)
    check("guess: the legacy body still asks something",
          fixed.rstrip().endswith("?"), fixed)


# ── 2. THE DESCRIPTOR: say what it is, do not ask as if nobody knows ────────
def test_deepseek():
    body = cm.build_body(
        5300, DEEPSEEK_MERCHANT, "2 Oct", "2205",
        checked=["descriptor: matched 'deepseek' -> Software & Online Services (conf 0.80)",
                 "records:ledger: nothing filed for this one"],
        category="Software & Online Services", category_source="descriptor")
    low = body.lower()
    check("deepseek: the body names the merchant", "deepseek" in low, body)
    check("deepseek: it states what the descriptor determines", "software & online services" in low, body)
    check("deepseek: it does NOT ask what the charge was, as if unknown",
          "what was it" not in low and "what was this" not in low, body)
    check("deepseek: it asks only whether that reading is right",
          "is that right" in low, body)
    check("deepseek: the question mark survives", body.rstrip().endswith("?"), body)
    check("deepseek: one amount, one card",
          len(AMOUNT_RE.findall(body)) == 1 and len(re.findall(r"card ending", body)) == 1, body)

    # The descriptor rung lives in merchant_resolve.py, not in charge_msg.py, so with no
    # determination handed in the only requirement here is that no guess is emitted.
    bare = cm.build_body(5300, DEEPSEEK_MERCHANT, "2 Oct", "2205")
    check("deepseek, nothing determined: no guess is invented",
          "guess" not in bare.lower() and "shop supplies" not in bare.lower(), bare)


# ── 2b. WHAT THE BODY MAY STATE AS A FINDING ────────────────────────────────
def test_stated_reading():
    """Only a reading the resolver stands behind is ever stated in a body.

    `provisional` means two categories fit, and `purchase is False` means the descriptor names
    a reversal -- stating either would put a category in his text that our own record does not
    support, which is worse than asking because it looks like diligence.
    """
    ok = {"solved": True, "category": "Gas & Fuel", "confidence": 0.80, "source": "descriptor"}
    check("stated: a settled descriptor reading is stated",
          cfo.stated_reading(ok) == ("Gas & Fuel", "descriptor"), repr(cfo.stated_reading(ok)))
    prov = dict(ok, provisional=True)
    check("stated: a PROVISIONAL reading is not stated (two categories fit)",
          cfo.stated_reading(prov) == ("", ""), repr(cfo.stated_reading(prov)))
    rev = dict(ok, category="Fees & Adjustments", purchase=False)
    check("stated: a reversal is not stated as a purchase",
          cfo.stated_reading(rev) == ("", ""), repr(cfo.stated_reading(rev)))
    check("stated: an unsolved reading is not stated",
          cfo.stated_reading({"solved": False, "category": "Gas & Fuel"}) == ("", ""))
    check("stated: nothing at all states nothing", cfo.stated_reading(None) == ("", ""))
    ent = {"solved": True, "entity": "300 Data Recovery", "confidence": 0.93, "source": "aliases"}
    check("stated: an identified vendor is stated",
          cfo.stated_reading(ent) == ("300 Data Recovery", "aliases"))


# ── 3. WHAT WAS CHECKED, AND NOTHING INVENTED ───────────────────────────────
def test_checked_clause():
    body = cm.build_body(5795, "Fuel", "28 Aug", "9650", checked=CHECKED_FUEL)
    low = body.lower()
    check("checked: names the sources it read",
          "i checked our ledger and your past answers" in low, body)
    check("checked: says the rest came up empty",
          "the descriptor is all i have" in low, body)
    check("checked: the charge is still named first",
          low.startswith("cfo: 57.95 at fuel"), body)

    bare = cm.build_body(5795, "Fuel", "28 Aug", "9650")
    check("unchecked: NO claim of diligence is invented",
          "checked" not in bare.lower(), bare)

    # A rung that failed did not look, so it must never be claimed as checked.
    partial = cm.build_body(5795, "Fuel", "28 Aug", "9650",
                            checked=["research:web: failed (timeout)",
                                     "records:ledger: nothing for fuel"])
    check("checked: a FAILED rung is not claimed",
          "the web" not in partial.lower(), partial)
    check("checked: the rung that did run still is",
          "our ledger" in partial.lower(), partial)


# ── 4. ONE QUESTION, ONE THING ──────────────────────────────────────────────
def test_one_charge():
    fixed = cm.enforce_one_charge(MESSY)
    low = fixed.lower()
    check("one: no message count ('+1 more')", "+1 more" not in low and "more)" not in low, fixed)
    check("one: no second merchant ('also this merchant')",
          "also this merchant" not in low, fixed)
    check("one: no email subject line",
          "your receipt for the order you placed" not in low, fixed)
    check("one: no grouped total", "total" not in low, fixed)
    check("one: exactly one amount", len(AMOUNT_RE.findall(fixed)) == 1, fixed)
    check("one: exactly one card", len(re.findall(r"card ending", fixed)) == 1, fixed)
    check("one: exactly one date of charge", len(re.findall(r"on \d+ \w+", fixed)) == 1, fixed)
    check("one: still a question", fixed.rstrip().endswith("?"), fixed)

    # A body that announces a second charge with a different amount loses it.
    two = cm.enforce_one_charge(
        "CFO [ask-1]: 57.95 at Fuel on 28 Aug, card ending 9650. "
        "22.10 at Shell on 30 Aug, card ending 2205. What was this purchase for?")
    check("one: a second charge with a different amount is dropped",
          "22.10" not in two and "shell" not in two.lower(), two)
    check("one: the first charge and the question survive",
          "57.95" in two and two.rstrip().endswith("?"), two)


# ── 5. THE SUPPRESSION IS KEYED ON THE CHARGE, NOT THE SHOP ─────────────────
def _row(**kw) -> dict:
    base = {
        "asked_at": "2026-10-19T11:00:00+00:00",
        "merchant_key": "fuel",
        "transaction_id": "t-a",
        "account_id": "personal-amex-22005",
        "amount_cents": 5795,
        "transaction_date": "2026-08-28",
        "sent": 1,
        "provider_ok": 1,
        "provider_detail": '{"dry_run": false}',
        "auto_resolved": 0,
    }
    base.update(kw)
    return base


def test_suppression():
    now = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)
    charge_a = cfo.charge_key(transaction_id="t-a")
    charge_b = cfo.charge_key(transaction_id="t-b")

    # ONE answer about a shop must not silence the next charge there.
    sup = cfo.ask_suppression([_row()], now=now)
    check("suppression: the charge that was asked is suppressed", charge_a in sup["keys"])
    check("suppression: a DIFFERENT charge at the SAME shop is still askable",
          charge_b not in sup["keys"])
    check("suppression: the keys are charges, not merchant names",
          "fuel" not in sup["keys"])

    # The same charge twice is ONE ask.
    sup_twice = cfo.ask_suppression([_row(), _row()], now=now)
    check("suppression: the same charge twice is asked once", len(sup_twice["keys"]) == 1)

    # The tuple fallback: two charges at one shop, one card, different amount and date.
    key_pair = (cfo.charge_key(account_id="personal-amex-22005", amount_cents=5795,
                               date="2026-08-28"),
                cfo.charge_key(account_id="personal-amex-22005", amount_cents=1299,
                               date="2026-10-01"))
    check("suppression: two charges at one shop have different identities",
          key_pair[0] != key_pair[1], repr(key_pair))
    row_no_id = _row(transaction_id=None, account_id="personal-amex-22005")
    sup_no_id = cfo.ask_suppression([row_no_id], now=now)
    check("suppression: the (account, amount, date) fallback still suppresses its own charge",
          key_pair[0] in sup_no_id["keys"] and key_pair[1] not in sup_no_id["keys"])

    # A dry run asked nobody.
    dry = _row(sent=0, provider_ok=1, provider_detail='{"dry_run": true, "rc": 0}')
    check("suppression: a DRY RUN suppresses nothing",
          cfo.ask_suppression([dry], now=now)["keys"] == set())

    # A refusal is not an ask; it silences the channel briefly, then stops.
    refused = _row(sent=0, provider_ok=0, provider_detail='{"rc": 1}')
    check("suppression: a fresh refusal suppresses (the channel was busy)",
          charge_a in cfo.ask_suppression([refused], now=now)["keys"])
    stale = dict(refused, asked_at="2026-10-19T00:00:00+00:00")     # 12 h > 6 h floor
    check("suppression: a refusal stops suppressing after the silence window",
          cfo.ask_suppression([stale], now=now)["keys"] == set())

    # A sent ask older than the re-ask window may be asked again.
    old = _row(asked_at="2026-10-15T11:00:00+00:00")               # 4 days > 48 h
    check("suppression: a sent ask older than the re-ask window comes back",
          cfo.ask_suppression([old], now=now)["keys"] == set())

    # Our own records ANSWERED the shop: that closes the MERCHANT, not just the charge.
    # The other direction of the same defect -- asking about a shop we already know is what
    # he called "a little more research before you ask me".
    answered = _row(sent=0, provider_ok=None, auto_resolved=1)
    sup_auto = cfo.ask_suppression([answered], now=now)
    check("suppression: an auto-resolved charge suppresses itself",
          charge_a in sup_auto["keys"])
    check("suppression: ... and closes the whole merchant",
          "fuel" in sup_auto["resolved_merchants"])
    check("suppression: ... and is never treated as a charge he was ASKED",
          sup_auto["ids"] == set())

    # A shop at the ask ceiling is a preference, never a suppression.
    at_ceiling = cfo.ask_suppression(
        [_row(transaction_id="t-1"), _row(transaction_id="t-2")], now=now)
    check("suppression: a shop at the ask ceiling is flagged for ranking",
          "fuel" in at_ceiling["over_ceiling"])
    check("suppression: ... and a new charge there is still askable",
          cfo.charge_key(transaction_id="t-9") not in at_ceiling["keys"])


# ── 6. THE SELECTOR: a second charge at an answered shop is still askable ───
LEDGER_SCHEMA = """
CREATE TABLE transactions(id TEXT PRIMARY KEY, entity_id TEXT, account_id TEXT,
  account_name TEXT, normalized_merchant TEXT, amount_cents INTEGER, transaction_date TEXT,
  duplicate_of_transaction_id TEXT, merchant_name TEXT, description TEXT, raw_payload_json TEXT);
CREATE TABLE transaction_categories(transaction_id TEXT);
CREATE TABLE accounts(id TEXT PRIMARY KEY, last_four TEXT);
INSERT INTO accounts VALUES ('personal-amex-22005','22005');
"""


def _day(days_ago: int) -> str:
    return (date.today() - timedelta(days=days_ago)).isoformat()


def test_selector_end_to_end():
    """The same defect through the real path, on a ledger this file makes itself.

    `ask_suppression()` being right is necessary and not sufficient: the SELECTOR has to
    offer the second charge, the COMPOSER has to ask about that charge and not the first one,
    and `record()` has to file it under the charge it named. This walks all three, in a
    tempfile store that is thrown away, with no network and no live ledger.
    """
    ledger = Path(os.environ["CFO_ACCT_DB"])
    if ledger.exists():
        ledger.unlink()
    c = sqlite3.connect(ledger)
    c.executescript(LEDGER_SCHEMA)
    for tid, cents, days_ago in (("t1", 5795, 7), ("t2", 4299, 2)):
        c.execute("INSERT INTO transactions VALUES (?,?,?,?,?,?,?,NULL,'Fuel','FUEL 4412','{}')",
                  (tid, "lpt", "personal-amex-22005", "Blue Cash", "fuel", cents, _day(days_ago)))
    c.commit()
    c.close()

    rec, why, _ = cfo.next_question()
    check("selector: the first candidate is the shop's first charge",
          rec is not None and rec["transaction_id"] == "t1", "%r" % (rec and rec["transaction_id"],))
    if rec is None:
        return
    body = cfo.compose(rec, "ask-1", checked=["ledger: not_found", "comms: not_found"],
                       evidence=["nothing in our records names it"])
    check("selector: the question is about the charge it names", "57.95" in body, body)
    check("selector: and it carries what was checked", "i checked our ledger" in body.lower(), body)
    cfo.record(rec, body, "ask-1", sent=True, res={"rc": 0, "dry_run": False})

    # THE SAME CHARGE IS NOT ASKED TWICE ...
    rec2, why2, _ = cfo.next_question()
    check("selector: the charge that was answered is not asked again",
          rec2 is None or rec2["transaction_id"] != "t1",
          "%r / %s" % (rec2 and rec2["transaction_id"], why2))
    # ... AND THE SECOND CHARGE AT THE SAME SHOP STILL IS.
    check("selector: a SECOND charge at the same shop is askable",
          rec2 is not None and rec2["transaction_id"] == "t2",
          "%r / %s" % (rec2 and rec2["transaction_id"], why2))
    if rec2 is not None:
        body2 = cfo.compose(rec2, "ask-2", checked=["ledger: not_found"])
        check("selector: the second question is about the SECOND charge",
              "42.99" in body2 and "57.95" not in body2, body2)
        cfo.record(rec2, body2, "ask-2", sent=True, res={"rc": 0, "dry_run": False})
        rec3, why3, d3 = cfo.next_question()
        check("selector: once both are answered the shop is exhausted",
              rec3 is None, "%r / %s" % (rec3 and rec3["transaction_id"], why3))

    # The store knows the identity it suppressed, on the charge, with the account.
    store = sqlite3.connect(os.environ["CFO_ASK_DB"])
    cols = [r[1] for r in store.execute("PRAGMA table_info(ask)")]
    rows = list(store.execute("SELECT transaction_id, account_id, amount_cents FROM ask"))
    store.close()
    check("selector: the store records the account a charge was on", "account_id" in cols, str(cols))
    check("selector: the store records the CHARGE, and its own amount",
          ("t1", "personal-amex-22005", 5795) in rows, repr(rows))


# ── 7. THE CEILING, WITHOUT CUTTING A WORD ──────────────────────────────────
def test_ceiling():
    merchant = " ".join(["Alpha"] * 40)
    head = "CFO: 12.00 at %s on 1 Jan, card ending 1234." % merchant
    body = cm.render(head, ask=cm.DEFAULT_ASK, limit=120)
    check("ceiling: the body fits the ceiling", len(body) <= 120, "%d: %s" % (len(body), body))
    check("ceiling: it still ends in a question", body.rstrip().endswith("?"), body)
    check("ceiling: it ends a sentence", body.rstrip()[-1] in ".?!", body)

    allowed = set(merchant.lower().split())
    allowed |= {w.strip(".,?") for w in cm.DEFAULT_ASK.lower().split()}
    allowed |= {"cfo:", "12.00", "at", "on", "1", "jan", "card", "ending", "1234"}
    cut = [w for w in body.lower().split() if w.strip(".,?!") not in allowed]
    check("ceiling: not one word is cut in half", not cut, repr(cut))

    # Evidence gives way before the question does.
    long_evidence = ["I checked our ledger, your past answers and the receipts - "
                     + ("and nothing there names it " * 8) + "."]
    with_ev = cm.render("CFO: 5.00 at Fuel on 1 Jan, card ending 1234.",
                        evidence=long_evidence, ask=cm.DEFAULT_ASK, limit=120)
    check("ceiling: over-long evidence is dropped, not truncated",
          "i checked" not in with_ev.lower() and len(with_ev) <= 120, with_ev)
    check("ceiling: and the question survives it", with_ev.rstrip().endswith("?"))

    full = cm.build_body(5795, "Fuel", "28 Aug", "9650", checked=CHECKED_FUEL)
    check("ceiling: a real body is well inside the hard ceiling",
          len(full) <= cm.RENDER_CEILING, "%d: %s" % (len(full), full))


# ── 8. THE PUBLIC SHAPES STILL WORK ────────────────────────────────────────
def test_public_shapes():
    for name in ("connect", "card_last4", "bank_words", "order_match", "email_match",
                 "fmt_money", "fmt_day", "compose", "render", "build_body",
                 "enforce_one_charge", "checked_clause", "sources_phrase"):
        check("public: charge_msg.%s exists" % name, callable(getattr(cm, name, None)))
    for name in ("compose", "next_question", "charge_key", "row_charge_key",
                 "ask_suppression", "find_pending", "record", "gate", "merchant_key",
                 "stated_reading", "resolved_enough"):
        check("public: cfo-ask.%s exists" % name, callable(getattr(cfo, name, None)))

    # The ladder's own threshold is another agent's change and must stay as it is: a
    # descriptor reading is a CLASSIFICATION and clears its own bar; an IDENTIFICATION clears
    # 0.85; a provisional or reversal reading is never enough.
    desc = {"solved": True, "category": "Gas & Fuel", "confidence": 0.80, "source": "descriptor"}
    check("threshold: a descriptor reading at 0.80 stays quiet (the ladder's own rule)",
          cfo.resolved_enough(desc) is True)
    check("threshold: a provisional reading is never enough",
          cfo.resolved_enough(dict(desc, provisional=True)) is False)
    check("threshold: a DEFINITE reversal is enough - asking about a refund is the complaint",
          cfo.resolved_enough(dict(desc, purchase=False)) is True)

    # Every new argument is a KEYWORD with a default: the two positional call shapes other
    # files use -- charge_msg.compose(conn, merchant) in textwork.py, and cfo-ask's own
    # compose(rec, ref, order_lines) -- keep working untouched.
    params = list(inspect.signature(cm.compose).parameters.values())
    check("shape: charge_msg.compose still takes (conn, merchant_key)",
          [p.name for p in params[:2]] == ["conn", "merchant_key"])
    check("shape: every later charge_msg.compose argument has a default",
          all(p.default is not inspect.Parameter.empty for p in params[2:]))
    cparams = list(inspect.signature(cfo.compose).parameters.values())
    check("shape: cfo-ask.compose still takes (rec, ref, order_lines)",
          [p.name for p in cparams[:3]] == ["rec", "ref", "order_lines"])
    check("shape: every later cfo-ask.compose argument has a default",
          all(p.default is not inspect.Parameter.empty for p in cparams[3:]))
    check("shape: email_match keeps its signature (merchant_resolve calls it)",
          list(inspect.signature(cm.email_match).parameters) == ["merchant", "when", "days"])


def main() -> int:
    try:
        for fn in (test_no_guess, test_deepseek, test_stated_reading, test_checked_clause,
                   test_one_charge, test_suppression, test_selector_end_to_end, test_ceiling,
                   test_public_shapes):
            print("\n-- %s --" % fn.__name__)
            fn()
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
    total = "FAILED: %d check(s)" % len(FAILURES)
    print("\n%s" % ("all checks passed" if not FAILURES else total))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())

