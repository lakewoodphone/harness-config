#!/usr/bin/env python3
"""vendor-aliases.py — has the owner already answered about this vendor, under any spelling?

WHY (measured 2026-10-02). The owner answered a charge question with
"that sounds like $300 data recovery we do business with them all the time". The ledger holds
that ONE vendor under FIVE merchant strings:

    data recovery                              10 charges, all categorised
    sq 300 data recovery gosq com ca            8 charges, 2 uncategorised
    sq 300 data recovery                        4 charges, 2 uncategorised
    data reclos                                 2 charges, all categorised
    300 data recovery los angeles ca            1 charge,  1 uncategorised ($520, 2026-07-09)

25 charges, **5 still uncategorised**, and none of the uncategorised ones can see the answer
that was already given, because they do not share a merchant string with it. So the same vendor
gets asked about again as if it were new — which is how "you should have that on record
already" became true.

This answers one question, for every consumer: *which vendors has the owner already answered
about, and under what spellings?* It is READ-ONLY and it only reports; deciding to auto-file
from it is a separate, deliberate step.

USAGE
    vendor-aliases.py                       list every answered vendor and its spellings
    vendor-aliases.py --vendor "data reclos"  answers for one spelling
    vendor-aliases.py --json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from pathlib import Path

LEDGER = Path(os.environ.get("CFO_ACCT_DB",
                             Path.home() / "accounting-data" / "live" / "accounting.db"))
CFO_ASK = Path(os.environ.get("CFO_ASK_DB", Path.home() / ".cfo-asks" / "asks.db"))

# Spellings that are the SAME vendor but share almost no characters. A normaliser cannot
# discover these; they are knowledge, and they come from an owner answer or a human note.
# Keep this list SHORT and always attributable: every entry cites where it came from.
KNOWN_SAME_VENDOR = (
    {
        "canonical": "300 Data Recovery (Los Angeles)",
        "variants": ("data recovery", "data reclos", "sq 300 data recovery",
                     "sq 300 data recovery gosq com ca",
                     "300 data recovery los angeles ca", "300dollardatarecovery.com"),
        "evidence": ("owner answer 2026-10-02T17:45Z in reply to cfo-ask #16: \"that sounds "
                     "like $300 data recovery we do business with them all the time\"; plus "
                     "Jotform receipts 2026-09-25/30 and 300DDR tickets #73890/#73896/#74114/#74115"),
    },
)


def _norm(text: str) -> str:
    """Same rule as cfo-ask.py::merchant_key, so keys agree between writers."""
    key = re.sub(r"[^a-z0-9 ]+", " ", (text or "").lower())
    return re.sub(r"\s+", " ", key).strip()[:48]


_LOOKUP = None


def _build_lookup() -> dict:
    """variant-key -> {canonical, evidence}. Static knowledge plus what the ask store holds."""
    global _LOOKUP
    if _LOOKUP is not None:
        return _LOOKUP
    out: dict = {}
    for group in KNOWN_SAME_VENDOR:
        for v in group["variants"]:
            out[_norm(v)] = {"canonical": group["canonical"], "evidence": group["evidence"]}

    # Anything the owner has actually answered about, from the ask store, joins its group by
    # name so a variant recorded later is still recognised.
    try:
        if CFO_ASK.exists():
            c = sqlite3.connect("file:%s?mode=ro" % CFO_ASK, uri=True, timeout=10)
            c.row_factory = sqlite3.Row
            try:
                for r in c.execute(
                        "SELECT merchant_key, merchant, answer FROM ask "
                        "WHERE answered_at IS NOT NULL"):
                    k = _norm(r["merchant_key"] or r["merchant"] or "")
                    if not k:
                        continue
                    canonical = out.get(k, {}).get("canonical") or (r["merchant"] or "")
                    out.setdefault(k, {"canonical": canonical,
                                       "evidence": "owner answered this on %s"
                                                   % str(r["answer"] or "")[:60]})
            finally:
                c.close()
    except Exception:
        pass
    _LOOKUP = out
    return out


def canonical_for(merchant: str) -> dict | None:
    """{canonical, evidence} if the owner (or a note) has placed this spelling, else None."""
    return _build_lookup().get(_norm(merchant))


def _ledger_counts(variant_to_canonical: dict) -> dict:
    """canonical -> {charges: n, variants: set}. `variant_to_canonical` maps a NORMALISED
    spelling to its canonical name. The first version passed the wrong mapping (canonical ->
    dict), so nothing ever matched and every vendor reported 0 charges -- a silent zero that
    read like "this vendor has no charges"."""
    counts: dict = {}
    if not LEDGER.exists():
        return counts
    try:
        c = sqlite3.connect("file:%s?mode=ro" % LEDGER, uri=True, timeout=15)
        c.row_factory = sqlite3.Row
        try:
            for r in c.execute("SELECT normalized_merchant m FROM transactions "
                               "WHERE duplicate_of_transaction_id IS NULL"):
                raw = r["m"] or ""
                canonical = variant_to_canonical.get(_norm(raw))
                if canonical:
                    e = counts.setdefault(canonical, {"charges": 0, "variants": set()})
                    e["charges"] += 1
                    e["variants"].add(raw)
        finally:
            c.close()
    except Exception:
        pass
    return counts


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vendor")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    lookup = _build_lookup()
    if args.vendor:
        hit = canonical_for(args.vendor)
        if args.json:
            print(json.dumps(hit, indent=1))
        else:
            print("%r -> %s" % (args.vendor, hit["canonical"] if hit else "not placed"))
            if hit:
                print("   evidence: %s" % hit["evidence"])
        return 0 if hit else 1

    # group by canonical and report the ledger side by side
    groups: dict = {}
    for k, v in lookup.items():
        groups.setdefault(v["canonical"], {"variants": set(), "evidence": v["evidence"]})
        groups[v["canonical"]]["variants"].add(k)
    counts = _ledger_counts({k: v["canonical"] for k, v in lookup.items()})

    if args.json:
        print(json.dumps({c: {"variants": sorted(g["variants"]),
                              "charges": counts.get(c, {}).get("charges", 0)}
                          for c, g in groups.items()}, indent=1))
        return 0

    print("vendors the owner (or a note) has placed, and the spellings they cover:")
    for canonical, g in sorted(groups.items()):
        n = counts.get(canonical, {}).get("charges", 0)
        print("\n  %s" % canonical)
        print("    %d charge(s) in the ledger across %d spelling(s)" % (n, len(g["variants"])))
        for v in sorted(g["variants"]):
            print("      - %s" % v)
        print("    evidence: %s" % g["evidence"][:150])
    return 0


if __name__ == "__main__":
    sys.exit(main())
