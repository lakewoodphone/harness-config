#!/usr/bin/env python3
"""test-merchant-honesty.py — a merchant is only "solved" when something actually answered it.

Run:  python test-merchant-honesty.py     (from this directory)
Exit: 0 all passed, 1 any failure. Prints "N passed".

NO NETWORK, NO REAL STORES. Every store this touches is a tempfile this script creates;
`merchant_resolve`'s module-level paths are repointed at a tempdir before anything runs, and
`order_evidence` is switched off so no mailbox is read. No accounting database is required:
the tests that need one use temp copies or call the pure helpers directly.

What it pins, and why each one is here (all measured 2026-10-15 on the live authority,
`merchant_resolve.py --no-research --why`):

  1. `_non_answer` recognises the reply that was counted as an answer to `adjust membership
     fee`: "I don't know. I want you to figure this out and give me more details..."
  2. `_non_answer` does NOT flag a real answer ("It was shop supplies, 2 hard drives...").
     A test that only ever returns True would silently turn every answered ask into a
     question again.
  3. `_non_answer` recognises the reply counted as the answer to `api`: "Didn't we file a
     few days ago? What are you talking about?"
  4. The descriptor rung maps FUEL, PASSNY TOLLBYMAI and the DeepSeek legal name.
  5. "ADJUST MEMBERSHIP FEE" reports a REVERSAL, never a membership purchase: the weaker
     of the two readings wins and `purchase` is False.
  6. A non-answer-only ask history leaves `photo` solved=False — the defect itself.
  7. An alias row with no category AND no entity leaves solved=False and records the vendor
     separately as `known_vendor`.
  8. Regressions: a real answered ask still resolves (`newegg`), and the descriptor rung
     never fires over a merchant a stronger rung already solved (DeepSeek -> vendor list).
"""

import importlib.util
import os
import sqlite3
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PASSED = 0
FAILED = []


def ok(name, cond, detail=""):
    global PASSED
    if cond:
        PASSED += 1
        print(f"  PASS  {name}")
    else:
        FAILED.append(name)
        print(f"  FAIL  {name}  {detail}")


def load():
    spec = importlib.util.spec_from_file_location(
        "merchant_resolve_under_test", os.path.join(HERE, "merchant_resolve.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def make_ask_store(path, rows):
    """cfo-ask's shape: `ask` with a `merchant_key` column. Fresh every time it is called."""
    if os.path.exists(path):
        os.remove(path)
    c = sqlite3.connect(path)
    try:
        c.executescript("""
            CREATE TABLE ask (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              merchant_key TEXT, merchant TEXT, amount_cents INTEGER,
              asked_at TEXT, answered_at TEXT, answer TEXT
            );
        """)
        c.executemany(
            "INSERT INTO ask (merchant_key, merchant, asked_at, answered_at, answer) "
            "VALUES (?, ?, ?, ?, ?)", rows)
        c.commit()
    finally:
        c.close()


def make_alias_store(mr, path, rows):
    if os.path.exists(path):
        os.remove(path)
    ok_, detail = mr.ensure_alias_store(path)
    assert ok_, detail
    c = sqlite3.connect(path)
    try:
        c.executemany(
            "INSERT INTO alias (merchant_key, entity, category, source, evidence, learned_at, "
            "learned_from) VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
        c.commit()
    finally:
        c.close()


def checked_for(res, method):
    for line in res.get("checked") or []:
        if line.startswith(method + ":"):
            return line
    return ""


def main():
    tmp = tempfile.mkdtemp(prefix="merchant-honesty-")
    mr = load()

    # ── NOTHING REAL. Repoint every store at the tempdir before the first call. ──────────
    asks_db = os.path.join(tmp, "asks.db")
    empty_asks = os.path.join(tmp, "no-such-asks.db")
    aliases_db = os.path.join(tmp, "aliases.db")
    mr.CFO_ASK_DB = type(mr.CFO_ASK_DB)(asks_db)
    mr.OWNER_ASK_DB = type(mr.OWNER_ASK_DB)(empty_asks)
    mr.ALIAS_DB = type(mr.ALIAS_DB)(aliases_db)
    mr.ACCT_DB = type(mr.ACCT_DB)(os.path.join(tmp, "no-such-accounting.db"))
    mr.order_evidence = None                      # no mailbox is read by this test
    os.environ["SECRETARY_DB"] = os.path.join(tmp, "no-such-authority.db")
    os.environ["MERCHANT_RESOLVE_RESEARCH"] = "0"

    # ── 1-3. an answer is not the same thing as an `answer` column with text in it ───────
    print("\n_non_answer")
    is_non, cue = mr._non_answer(
        "I don't know. I want you to figure this out and give me more details...")
    ok("1 the 'I don't know / figure this out' reply is a non-answer", is_non, f"got {is_non!r}")
    ok("1b the cue that caught it is named", is_non and "know" in cue, f"cue={cue!r}")

    is_non2, cue2 = mr._non_answer("It was shop supplies, 2 hard drives, 2TB each")
    ok("2 a real answer is NOT a non-answer", is_non2 is False, f"got {is_non2!r} cue={cue2!r}")

    is_non3, cue3 = mr._non_answer(
        "Didn't we file a few days ago? What are you talking about?")
    ok("3 'Didn't we ... what are you talking about' is a non-answer", is_non3, f"got {is_non3!r}")
    ok("3b the cue that caught it is named", is_non3 and cue3 in (
        "didn't we", "what are you talking about"), f"cue={cue3!r}")

    ok("3c an empty reply is not classified as a non-answer", mr._non_answer("")[0] is False)
    ok("3d a curly apostrophe is read as a straight one",
       mr._non_answer("I don\u2019t know what that was")[0] is True)

    # ── 4-5. the descriptor rung ────────────────────────────────────────────────────────
    print("\ndescriptor rung")
    cases = (
        ("FUEL", "Gas & Fuel"),
        ("PASSNY TOLLBYMAI", "Parking & Tolls"),
        ("hangzhou-deepseek-artificial-intelligence-co.,-ltd", "Software & Online Services"),
    )
    for raw, expect in cases:
        cand, detail = mr._from_descriptor(raw)
        ok(f"4 {raw!r} -> {expect}",
           bool(cand) and cand["category"] == expect, f"got {cand and cand['category']!r} / {detail}")
        ok(f"4b {raw!r} carries the matched token as evidence",
           bool(cand) and cand.get("descriptor_token")
           and any(cand["descriptor_token"] in e for e in cand["evidence"]), f"{detail}")
        ok(f"4c {raw!r} confidence is capped at 0.80",
           bool(cand) and cand["confidence"] <= mr.CONF_DESCRIPTOR_MAX <= 0.80,
           f"got {cand and cand['confidence']}")

    cand, detail = mr._from_descriptor("ADJUST MEMBERSHIP FEE")
    ok("5 'ADJUST MEMBERSHIP FEE' is read as a REVERSAL, not a purchase",
       bool(cand) and cand["category"] == "Fees & Adjustments" and cand["purchase"] is False,
        f"{detail}")
    ok("5b the weaker reading won: it is not reported as Subscriptions",
       bool(cand) and cand["category"] != "Subscriptions", f"{detail}")
    ok("5c the evidence says a bare 'adjust' is a reversal",
       bool(cand) and any("reversal" in e.lower() for e in cand["evidence"]), f"{detail}")
    ok("5d the stronger reading is still reported as an alternative, not hidden",
       bool(cand) and any(a["category"] == "Subscriptions" for a in cand["alternatives"]),
       f"{cand and cand['alternatives']}")
    ok("5e the rung does not close the ladder on a two-reading descriptor",
       bool(cand) and cand["provisional"] is True, f"{detail}")

    cand, detail = mr._from_descriptor("newegg.com")
    ok("4d a descriptor with no known token finds nothing and says so",
       cand is None and "no token" in detail, f"{cand} / {detail}")

    # The truncation rule allows PASSNY to read as PASS, so it must NOT allow the same
    # letters in the MIDDLE of a word to do it. These are the false positives that would
    # file a charity as a toll and a bank as an AI vendor.
    cand, detail = mr._from_descriptor("COMPASSION INTERNATIONAL")
    ok("4e 'COMPASSION' is not a toll (the token is not a prefix or suffix of the word)",
       cand is None, f"{cand and cand['category']} / {detail}")
    cand, detail = mr._from_descriptor("CAPITAL ONE")
    ok("4f 'CAPITAL ONE' is not an AI vendor ('api' is inside 'capital')",
       cand is None, f"{cand and cand['category']} / {detail}")
    cand, detail = mr._from_descriptor("EZPASS NY")
    ok("4g a token at the END of a truncated word still matches ('PASS' in 'EZPASS')",
       bool(cand) and cand["category"] == "Parking & Tolls", f"{detail}")

    # ── 6. the defect itself: a non-answer-only history for `photo` ─────────────────────
    print("\nphoto - a reply about another merchant's business is not an answer")
    make_ask_store(asks_db, [
        ("photo", "photo", "2026-10-10T12:00:00Z", "2026-10-10T13:00:00Z",
         "I don't know. I want you to figure this out and give me more details..."),
    ])
    cand, why = mr._from_answered_asks("photo")
    ok("6 an answered ask whose reply is a non-answer contributes nothing", cand is None, f"{why}")
    ok("6b and says so in its own words",
       "was not an answer" in why, f"{why}")
    res = mr.resolve("photo", research=False)
    ok("6c photo is not solved", res["solved"] is False,
       f"solved={res['solved']} method={res['method']} conf={res['confidence']}")
    ok("6d the checked line names the non-answer rather than the merchant",
       "was not an answer" in checked_for(res, "records:owner-answer"),
       checked_for(res, "records:owner-answer"))

    # ── 8a. regression: a REAL answered ask still resolves ──────────────────────────────
    print("\nregression - a real answered ask")
    make_ask_store(asks_db, [
        ("acme supplies", "acme supplies", "2026-10-01T12:00:00Z", "2026-10-01T13:00:00Z",
         "It was shop supplies, 2 hard drives, 2TB each"),
    ])
    cand, why = mr._from_answered_asks("acme supplies")
    ok("8 a reply that IS an answer still resolves", cand is not None and
       cand["method"] == "records:owner-answer", f"{why}")
    res = mr.resolve("acme supplies", research=False)
    ok("8b and the resolve reports solved", res["solved"] is True,
       f"solved={res['solved']} method={res['method']}")

    # ── 7. an alias with no category and no entity is not an answer ─────────────────────
    print("\nalias with nothing in it")
    make_alias_store(mr, aliases_db, [
        ("mystery vendor", "", "", "owner-answer", "learned from a reply that named nothing",
         "2026-10-14T00:10:28Z", "ask-42"),
    ])
    res = mr.resolve("mystery vendor", research=False)
    ok("7 an alias with no category and no entity does NOT solve", res["solved"] is False,
       f"solved={res['solved']} source={res['source']} conf={res['confidence']}")
    ok("7b the vendor knowledge is recorded separately as known_vendor",
       bool(res.get("known_vendor")), f"known_vendor={res.get('known_vendor')!r}")
    ok("7c and the checked line says exactly what is missing",
       "nobody has ever said what it was for" in checked_for(res, "aliases"),
       checked_for(res, "aliases"))

    # ── 8b. regression: an alias he taught us still resolves even with no category ──────
    print("\nregression - the newegg alias, which is his own answer")
    make_alias_store(mr, aliases_db, [
        ("newegg com", "Newegg", "", "owner-answer",
         "learned from his answer 2026-10-14", "2026-10-14T00:10:28Z", "ask-31"),
    ])
    res = mr.resolve("newegg.com", research=False)
    ok("8c an alias naming the VENDOR still solves (no category needed)",
       res["solved"] is True and res["entity"] == "Newegg",
       f"solved={res['solved']} entity={res['entity']!r}")

    # ── the two merchants the owner answered himself, from the descriptor alone ────────
    print("\nthe descriptor alone answers these")
    res = mr.resolve("pass on", research=False)
    ok("9 'pass on' resolves from the descriptor alone",
       res["solved"] is True and res["category"] == "Parking & Tolls",
       f"solved={res['solved']} category={res['category']!r} method={res['method']}")
    ok("9b and the descriptor rung is the one that did it",
       res["method"] == "descriptor", res["method"])

    res = mr.resolve("adjust membership fee", research=False)
    ok("10 'adjust membership fee' is not claimed as a membership purchase",
       res["category"] == "Fees & Adjustments" and res["purchase"] is False,
       f"category={res['category']!r} purchase={res['purchase']}")
    ok("10b and the evidence handed to the asker says it is a reversal",
       any("reversal" in e.lower() for e in res["evidence"]), f"{res['evidence']}")

    # ── the descriptor rung never fires over a merchant a stronger rung already solved ─
    print("\nno firing over a solved merchant")
    res = mr.resolve("hangzhou-deepseek-artificial-intelligence-co.,-ltd", research=False)
    ok("11 the vendor list solves DeepSeek at its own confidence",
       res["solved"] is True and res["source"] == "vendor-list",
       f"source={res['source']} conf={res['confidence']}")
    ok("11b the descriptor rung stood down and said why",
       checked_for(res, "descriptor").startswith("descriptor: not needed"),
       checked_for(res, "descriptor"))
    ok("11c no descriptor evidence leaked into a vendor-list resolution",
       not any("statement descriptor" in e for e in res["evidence"]), f"{res['evidence']}")

    # ── every rung still appears in `checked`, whatever it found ──────────────────────
    print("\nchecked names every rung")
    res = mr.resolve("photo", research=False)
    missing = [m for m in mr.CHECKED_METHODS if not checked_for(res, m)]
    ok("12 every method in CHECKED_METHODS has a line", not missing, f"missing={missing}")
    ok("12b 'descriptor' is one of them", "descriptor" in mr.CHECKED_METHODS)
    ok("12c a miss still appears, it does not look unchecked",
       "no token that names a category" in checked_for(res, "descriptor"),
       checked_for(res, "descriptor"))

    # -- the descriptor rung may only emit categories the LEDGER holds -----------------
    # A rule that emits a name the categories table does not hold gets no category id, so
    # `planned_rows` stays empty and the charge is never actually filed while the resolver
    # reports solved=True. Measured 2026-10-19: the first version emitted four such names.
    print("\ndescriptor category names exist in the ledger")
    _emitted = {r["category"] for r in mr.DESCRIPTOR_RULES}
    _unknown = sorted(_emitted - _REAL_LEDGER_CATEGORIES)
    ok("13 every descriptor category is a real ledger category", not _unknown,
       f"not in the ledger: {_unknown}")

    print("\n%d passed" % PASSED)
    if FAILED:
        print("FAILED: %s" % ", ".join(FAILED))
        return 1
    return 0



#: Category names the authority's `categories` table actually holds (137 rows,
#: verified 2026-10-19). A descriptor rule may not emit anything outside this set.
_REAL_LEDGER_CATEGORIES = {'Groceries', 'Subscriptions', 'Insurance', 'Fees & Adjustments', 'Software & Online Services', 'Parking & Tolls', 'Gas & Fuel', 'Cash Withdrawals', 'Online Marketplace Purchases'}


if __name__ == "__main__":
    sys.exit(main())

