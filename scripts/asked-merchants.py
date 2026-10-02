#!/usr/bin/env python3
"""Make the two askers' "already asked" record TWO-WAY.

State after round 9: `owner-ask.py` reads `cfo-ask.py`'s sent merchants, so it will not
repeat a charge the CFO asked about. Nothing reads owner-ask's purchases, so the reverse
is still open — `cfo-ask.py` can ask about a charge `owner-ask.py` already put to him.
That is half of `P2830` and a third asker would reopen it entirely.

THIS is the smallest two-way record that does not invent a new store: a view over BOTH
existing stores, `~/.cfo-asks/asks.db` and `~/.owner-ask/asks.db`, answering one question
for every asker — *has this merchant already been put to the owner, by anyone?*

Read-only. No new file, no new state to keep in sync, so it cannot drift from the stores
it summarises. The normalisation is `cfo-ask.py::merchant_key` exactly, because a dedupe
key that differs between the writers is how `newegg`/`newegg.com` slipped past the first
attempt.
"""
from __future__ import annotations

import os
import re
import sqlite3
import sys
from pathlib import Path

CFO_DB = Path(os.environ.get("CFO_ASK_DB", Path.home() / ".cfo-asks" / "asks.db"))
OWNER_DB = Path(os.environ.get("OWNER_ASK_DB", Path.home() / ".owner-ask" / "asks.db"))


def merchant_key(name: str) -> str:
    """BYTE-IDENTICAL to cfo-ask.py::merchant_key. Do not 'improve' it in one place."""
    key = re.sub(r"[^a-z0-9 ]+", " ", (name or "").lower())
    key = re.sub(r"\s+", " ", key).strip()
    return key[:48]


def _ro(path: Path):
    c = sqlite3.connect("file:%s?mode=ro" % path, uri=True, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA busy_timeout=8000")
    return c


def asked_merchants() -> dict[str, list[str]]:
    """merchant_key -> list of "who asked it" labels. Never raises."""
    out: dict[str, list[str]] = {}

    def add(raw: str, who: str) -> None:
        k = merchant_key(raw)
        if not k:
            return
        out.setdefault(k, [])
        if who not in out[k]:
            out[k].append(who)

    try:
        if CFO_DB.exists():
            c = _ro(CFO_DB)
            try:
                for (m,) in c.execute("SELECT DISTINCT merchant_key FROM ask WHERE sent=1"):
                    add(m, "cfo-ask")
            finally:
                c.close()
    except Exception as exc:  # noqa: BLE001 -- a dedupe read must never block a send
        print("asked_merchants: cfo-ask store unreadable (%s)" % exc, file=sys.stderr)

    try:
        if OWNER_DB.exists():
            c = _ro(OWNER_DB)
            try:
                # owner-ask stores purchases as source='purchase', source_id='m:<merchant>'
                for (src, sid) in c.execute(
                        "SELECT DISTINCT source, source_id FROM ask "
                        "WHERE sent=1 AND source LIKE 'purchase%'"):
                    m = str(sid or "")
                    if m.startswith("m:"):
                        m = m[2:]
                    add(m, "owner-ask")
            finally:
                c.close()
    except Exception as exc:  # noqa: BLE001
        print("asked_merchants: owner-ask store unreadable (%s)" % exc, file=sys.stderr)

    return out


def already_asked(merchant: str) -> list[str]:
    """Who has already put this merchant to the owner. Empty means nobody has."""
    return asked_merchants().get(merchant_key(merchant), [])


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    m = asked_merchants()
    if argv and argv[0] == "--who":
        who = already_asked(argv[1] if len(argv) > 1 else "")
        print("%s -> %s" % (argv[1] if len(argv) > 1 else "", who or "nobody"))
        return 0
    print("asked merchants, by who asked (union of both stores)")
    for k in sorted(m):
        print("  %-46s %s" % (k, ", ".join(m[k])))
    print("  total: %d merchant(s)" % len(m))
    return 0


if __name__ == "__main__":
    sys.exit(main())
