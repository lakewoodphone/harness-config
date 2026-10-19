#!/usr/bin/env python3
"""Tests for the "his reply is not an answer" gate in `textdecide.py`.

Every text asserted here is quoted from the owner's own corpus - the two texts the block
was built for are the first two cases. The assertions are on the VERDICT, not on the
wording of a reason, except where the reason is the thing that gets quoted into the
ledger.

Pure functions only: no network, no model, no API, and NO SQLITE AT ALL. `build_alias`
returns a row and writes nothing (`write_alias` is the writer, and it is never called
here). Both stores these modules know about are pointed at a throwaway tempdir anyway, so
even a bug in this file cannot reach `~/.cfo-asks` or `~/.owner-text`.

Run:  cd base && python test-attribute-reply.py      (exit 0 = every case passed)
"""
import os
import sys
import tempfile

_TMP = tempfile.mkdtemp(prefix="attribute-reply-test-")
# Belt and braces: if anything in textdecide ever writes, it writes here and not into a
# real store. Set BEFORE the import, because the paths are resolved when they are used.
os.environ["CFO_ALIAS_DB"] = os.path.join(_TMP, "aliases.db")
os.environ["SMS_INBOX_DB"] = os.path.join(_TMP, "inbox.db")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import textdecide as td  # noqa: E402

# --------------------------------------------------------------------------- #
# Fixtures. `merchant_key` is the shape `cfo-ask.py:merchant_key()` produces: the
# merchant's own words, lowercased. Nothing here is a real charge.
# --------------------------------------------------------------------------- #
ASK_HARD_DRIVES = {
    "merchant_key": "hard drives", "merchant": "Hard Drives", "amount": "114.04",
    "reference": "ask-1791747091",
    "body": "What was the $114.04 charge at Hard Drives on the card for?",
}
ASK_MICRO_CENTER = {
    "merchant_key": "micro center", "merchant": "Micro Center", "amount": "25.00",
    "reference": "ask-1791747100",
    "body": "What was the $25.00 charge at Micro Center for?",
}
# The ask whose body guesses a category. `_ask_guess` reads "My guess: shop supplies".
ASK_WITH_GUESS = {
    "merchant_key": "best buy", "merchant": "Best Buy", "amount": "114.04",
    "reference": "ask-1791747200",
    "body": "What was the $114.04 charge at Best Buy for? My guess: shop supplies",
}
ASK_DECISION = {  # no merchant: a decision question, never a purchase answer
    "reference": "ask-1791747300", "body": "Should I run this on the desktop tonight?",
}

# The corpus texts, verbatim.
TEXT_DONT_KNOW = ("I don't know. I want you to figure this out and give me more details. "
                  "Maybe check my emails or other places.")
TEXT_DIDNT_WE_FILE = "Didn't we file a few days ago? What are you talking about?"
TEXT_DOESNT_SEEM = "That doesn't seem like a smart question isn't that clearly gas?"
TEXT_SHOP_SUPPLIES = "It was shop supplies It was 2 hard drives each one 2 TB"
TEXT_WIFES_DRESS = "That was my wife's second holiday dress totally personal"
TEXT_GROCERIES = "That was just groceries"
TEXT_ARE_YOU_SERIOUS = ("Are you serious? It looks like easy pass to me and that's just "
                        "from your text. Why can't you figure that out?")


# --------------------------------------------------------------------------- #
# The harness: one line per case, a count at the end, exit 0 only if all passed.
# --------------------------------------------------------------------------- #
_RESULTS = []


def case(name, *checks):
    """One case: `checks` are (label, actual, expected) triples."""
    bad = []
    for label, actual, expected in checks:
        if actual != expected:
            bad.append("%s: got %r, wanted %r" % (label, actual, expected))
    _RESULTS.append((name, not bad, "; ".join(bad)))

    def show():
        print(("PASS  " if not bad else "FAIL  ") + name)
        for label, actual, expected in checks:
            print("        %-18s = %r" % (label, actual))
        if bad:
            for line in bad:
                print("        !! " + line)
    show()


def main() -> int:
    print("textdecide:", td.__file__)
    print("temp stores:", _TMP)
    print()

    # -- the two texts this whole block exists for -------------------------- #
    v, why = td.is_non_answer(TEXT_DONT_KNOW)
    r = td.attribute_reply(TEXT_DONT_KNOW, [ASK_HARD_DRIVES])
    case("1. \"I don't know. I want you to figure this out...\" ($114.04 ask)",
         ("is_non_answer", v, True),
         ("reason quotes it", "don't know" in why.lower(), True),
         ("inferred", r["inferred"], True),
         ("learnable", r["learnable"], False),
         ("closes", r["closes"], False),
         ("ask is still named", bool(r["ask"]), True))

    v, why = td.is_non_answer(TEXT_DIDNT_WE_FILE)
    r = td.attribute_reply(TEXT_DIDNT_WE_FILE, [ASK_MICRO_CENTER])
    case("2. \"Didn't we file a few days ago? What are you talking about?\" ($25.00 ask)",
         ("is_non_answer", v, True),
         ("reason quotes it", "didn't we" in why.lower(), True),
         ("inferred", r["inferred"], True),
         ("learnable", r["learnable"], False),
         ("closes", r["closes"], False))

    case("3. \"That doesn't seem like a smart question isn't that clearly gas?\"",
         ("is_non_answer", td.is_non_answer(TEXT_DOESNT_SEEM)[0], True),
         ("names a category but still refused", "gas" in TEXT_DOESNT_SEEM, True))

    case("7. \"Are you serious? ... Why can't you figure that out?\"",
         ("is_non_answer", td.is_non_answer(TEXT_ARE_YOU_SERIOUS)[0], True))

    # -- the answers that MUST still be answers ----------------------------- #
    category, cat_why = td.category_from(TEXT_SHOP_SUPPLIES)
    r = td.attribute_reply(TEXT_SHOP_SUPPLIES, [ASK_HARD_DRIVES, ASK_MICRO_CENTER])
    case("4. \"It was shop supplies It was 2 hard drives each one 2 TB\"",
         ("is_non_answer", td.is_non_answer(TEXT_SHOP_SUPPLIES)[0], False),
         ("category", category, "shop supplies"),
         ("strength", r["strength"], 3),
         ("inferred", r["inferred"], False),
         ("learnable", r["learnable"], True),
         ("closes", r["closes"], True))

    r0 = td.attribute_reply(TEXT_SHOP_SUPPLIES, [ASK_MICRO_CENTER])
    case("4b. the same text, the ONE open ask does not name it (strength 0)",
         ("strength", r0["strength"], 0),
         ("inferred stays True (provenance)", r0["inferred"], True),
         ("n_open", r0["n_open"], 1),
         ("learnable - sole-open-ask licence", r0["learnable"], True))

    r1 = td.attribute_reply(TEXT_SHOP_SUPPLIES,
                            [ASK_MICRO_CENTER, ASK_WITH_GUESS, ASK_DECISION])
    case("4c. the same text with THREE asks open -> strength 0 is ambiguous, teaches nothing",
         ("strength", r1["strength"], 0),
         ("n_open", r1["n_open"], 3),
         ("learnable", r1["learnable"], False),
         ("reason says why", "would be a guess" in r1["reason"], True))

    category, _ = td.category_from(TEXT_WIFES_DRESS)
    case("5. \"That was my wife's second holiday dress totally personal\"",
         ("is_non_answer", td.is_non_answer(TEXT_WIFES_DRESS)[0], False),
         ("category", category, "personal"))

    category, _ = td.category_from(TEXT_GROCERIES)
    case("6. \"That was just groceries\"",
         ("is_non_answer", td.is_non_answer(TEXT_GROCERIES)[0], False),
         ("category", category, "Groceries"))

    # -- no alias from a strength-0 / inferred attribution ------------------ #
    row = td.build_alias(TEXT_SHOP_SUPPLIES, ASK_HARD_DRIVES, inferred=True)
    print("        (build_alias above printed its refusal - that is the line under test)")
    case("8. strength-0 attribution must not produce an alias  [build_alias(inferred=True)]",
         ("row", row, None))

    # -- the ask's own guess is not his words ------------------------------- #
    row = td.build_alias(TEXT_DONT_KNOW, ASK_WITH_GUESS)
    print("        (build_alias above printed its refusal - that is the line under test)")
    case("9. \"My guess: shop supplies\" + a non-answer reply  -> no alias",
         ("row", row, None),
         ("non_answer", td.is_non_answer(TEXT_DONT_KNOW)[0], True))

    body = "That was for the 2 hard drives"
    row = td.build_alias(body, ASK_WITH_GUESS)
    print("        (build_alias above printed its refusal - that is the line under test)")
    case("10. an ANSWER-shaped text that names no category, ask guessed one -> no alias",
         ("is_non_answer", td.is_non_answer(body)[0], False),
         ("non-strict category is the guess", td.category_from(body, ASK_WITH_GUESS)[0],
          "shop supplies"),
         ("strict refuses the guess", td.category_from(body, ASK_WITH_GUESS,
                                                       strict=True)[0], None),
         ("row", row, None))

    case("11. category_from(strict=True) returns (None, why), never \"unknown\"",
         ("default returns unknown", td.category_from("Talk to me", {})[0], "unknown"),
         ("strict returns None", td.category_from("Talk to me", {}, strict=True)[0], None),
         ("strict why is a sentence",
          bool(td.category_from("Talk to me", {}, strict=True)[1]), True))

    # -- the precision gate: a hedge in front of a real answer stays an answer -- #
    hedged = "i told you that was shop supplies"
    case("12. \"i told you that was shop supplies\" is an answer with a hedge, not a refusal",
         ("is_non_answer", td.is_non_answer(hedged)[0], False),
         ("category", td.category_from(hedged)[0], "shop supplies"))

    # The long Data Reclos answer, quoted in textdecide's own ACT_RE comment. "research it"
    # appears inside a condition he is describing, which is not an instruction to us.
    reclos = ("You could do a little more research and if you would look into this and "
              "research it, you would see that this is the data recovery we discussed.")
    case("12b. the long Data Reclos answer is not refused as an instruction",
         ("is_non_answer", td.is_non_answer(reclos)[0], False),
         ("the phrase that would have matched",
          bool(td._NON_ANSWER_FAMILIES[1][1].search(reclos)), True))

    # -- best_ask is untouched, and build_alias still works for a real answer -- #
    ask, strength, hits = td.best_ask("hello there", [ASK_HARD_DRIVES, ASK_MICRO_CENTER])
    ask2, strength2, _ = td.best_ask("I was at micro center",
                                     [ASK_HARD_DRIVES, ASK_MICRO_CENTER])
    case("13. best_ask's published contract is unchanged",
         ("newest merchant ask wins the strength-0 fallback", ask.get("reference"),
          "ask-1791747091"),
         ("fallback strength", strength, 0),
         ("fallback hits", hits, []),
         ("content match still wins", ask2.get("reference"), "ask-1791747100"),
         ("content strength", strength2, 3))

    row = td.build_alias(TEXT_SHOP_SUPPLIES, ASK_HARD_DRIVES)
    case("14. a real answer still builds its row (the gates are not a blanket refusal)",
         ("row is not None", bool(row), True),
         ("merchant_key", (row or {}).get("merchant_key"), "hard drives"),
         ("category", (row or {}).get("category"), ""),  # NOT "shop supplies": the ledger holds 137 categories and that is not one of them (measured 2026-10-19). His phrase still lands in evidence.
         ("source", (row or {}).get("source"), "owner-answer"))

    # -- attribution order: an explicit reference outranks everything ------- #
    with_ref = "CFO [ask-1791747100] that was shop supplies"
    r = td.attribute_reply(with_ref, [ASK_HARD_DRIVES, ASK_MICRO_CENTER])
    case("15. an explicit reference in his text wins (strength 3, inferred False)",
         ("ask", (r["ask"] or {}).get("reference"), "ask-1791747100"),
         ("strength", r["strength"], 3),
         ("inferred", r["inferred"], False),
         ("match", r["match"], "explicit"))

    # -- nothing to attribute to is said out loud, not guessed at ----------- #
    r = td.attribute_reply(TEXT_SHOP_SUPPLIES, [ASK_DECISION])
    case("16. a decision question with no merchant is never the purchase answer",
         ("ask", r["ask"], None),
         ("learnable", r["learnable"], False),
         ("closes", r["closes"], False),
         ("reason says so", "no open ask" in r["reason"], True))

    # -- the sole-open-ask licence, asserted the three ways it must behave -- #
    # The rule is `not non_answer and strength >= 2 or n_open == 1`; these are the three
    # cases that would break it in either direction.
    one_open = td.attribute_reply(TEXT_GROCERIES, [ASK_HARD_DRIVES])
    three_open = td.attribute_reply(TEXT_GROCERIES,
                                    [ASK_HARD_DRIVES, ASK_MICRO_CENTER, ASK_WITH_GUESS])
    refused = td.attribute_reply("I don't know, figure it out", [ASK_HARD_DRIVES])
    case("18. the sole-open-ask licence (groceries / ambiguity / non-answer)",
         ("n_open=1 + groceries: learnable", one_open["learnable"], True),
         ("n_open=1 + groceries: still inferred", one_open["inferred"], True),
         ("n_open=1 + groceries: category", td.category_from(TEXT_GROCERIES)[0], "Groceries"),
         ("n_open=3 + groceries: learnable", three_open["learnable"], False),
         ("n_open=3 + groceries: n_open reported", three_open["n_open"], 3),
         ("n_open=1 + \"figure it out\": non_answer", refused["non_answer"], True),
         ("n_open=1 + \"figure it out\": learnable (gate beats the licence)",
          refused["learnable"], False))

    # -- the flag and the builder cannot disagree ------------------------- #
    # `learnable` is a PERMISSION, so it may never promise a row `build_alias` would then
    # refuse: every True must be paid for by a real row. build_alias' refusals are captured
    # instead of printed so this case stays one line.
    import contextlib
    import io

    def quiet_row(b, a, inferred):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            got = td.build_alias(b, a, inferred=inferred)
        return got, buf.getvalue().strip()

    agree, disagreements = True, []
    for body, asks, expected in (
            (TEXT_SHOP_SUPPLIES, [ASK_HARD_DRIVES], True),
            (TEXT_SHOP_SUPPLIES, [ASK_WITH_GUESS], True),
            (TEXT_GROCERIES, [ASK_HARD_DRIVES], True),
            (TEXT_GROCERIES, [ASK_HARD_DRIVES, ASK_MICRO_CENTER, ASK_WITH_GUESS], False),
            (TEXT_WIFES_DRESS, [ASK_WITH_GUESS], True),
            (TEXT_DIDNT_WE_FILE, [ASK_HARD_DRIVES], False)):
        verdict = td.attribute_reply(body, asks)
        row, _ = quiet_row(body, asks[0], False)
        if verdict["learnable"] != expected:
            agree = False
            disagreements.append("%r: learnable=%s, expected %s" % (
                body[:40], verdict["learnable"], expected))
        if verdict["learnable"] and not row:
            agree = False
            disagreements.append("%r: learnable True but build_alias returned None"
                                 % body[:40])
        if verdict["n_open"] != len(asks):
            agree = False
            disagreements.append("%r: n_open=%s for %d asks" % (
                body[:40], verdict["n_open"], len(asks)))
    case("17. learnable is a permission the builder honours (6 text/ask pairs)",
         ("all agree", agree, True),
         ("disagreements", disagreements, []))

    print()
    passed = sum(1 for _, ok, _ in _RESULTS if ok)
    failed = len(_RESULTS) - passed
    print("%d/%d cases passed, %d failed" % (passed, len(_RESULTS), failed))
    if failed:
        for name, ok, why_bad in _RESULTS:
            if not ok:
                print("  FAILED: %s -- %s" % (name, why_bad))
        return 1
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())

