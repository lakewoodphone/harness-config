#!/usr/bin/env python3
"""Correct the dormant-archive finding so its remedy cannot cause an incident.

MEASURED 2026-10-18. After fixing check-dsh-freshness.py's database default (doc s59), dormant-handoff
began producing a REAL finding again -- and its own prompt text was wrong in two ways:

  1. "The authoritative store is `secretary.db` via POST /api/v1/owner/dsh-sessions/ingest". The
     authoritative store is the company database at /root/authority.db (table dsh_sessions). The
     sentence points at the same dead copy that was just fixed.
  2. It says "A machine whose shipper has stopped is single-homed until this is fixed", and step 3
     says "fix the CAUSE". For `secratary` -- the FROZEN rollback anchor -- the shipper is stopped
     ON PURPOSE, and starting it is the exact incident AGENTS.md section 5 records (5,129 rows pushed
     into the anchor, and a rollback anchor that is no longer a clean cutover point).

So the prompt now names the frozen case and the sanctioned remedy: the bytes already arrive because
the AUTHORITY pulls them; only the PARSED projection stops, and that is filled from the authority
(ledger item 561).

Idempotent, parse-checked.
"""
import ast
import io
import sys

P = "/root/bin/sources/dormant-handoff.py"

OLD = '''                "2. The authoritative store is `secretary.db` via",
                "   `POST /api/v1/owner/dsh-sessions/ingest`; the shipper is",
                "   `scripts/push-dsh-sessions.mjs` (Windows tasks and the authority cron).",
                "   Do NOT read `~/dsh-archive/dsh-archive.db` — it is the retired `scp`",
                "   interim, frozen by design since 2026-09-11 19:16 (D42, L158b).",'''

NEW = '''                "2. The authoritative store is the company database at /root/authority.db on",
                "   secratary-cloud (table `dsh_sessions`), NOT a `secretary.db` copy -- reading a",
                "   copy is what made this source refuse for weeks. The shipper is",
                "   `scripts/push-dsh-sessions.mjs`.",
                "   Do NOT read `~/dsh-archive/dsh-archive.db` — it is the retired `scp`",
                "   interim, frozen by design since 2026-09-11 19:16 (D42, L158b).",
                "",
                "2b. FIRST ASK WHETHER THE MACHINE IS FROZEN. Read",
                "    settings/machines/host-posture.tsv. `secratary` has been the FROZEN rollback",
                "    anchor since 2026-10-11, its cron is masked ON PURPOSE, and starting it is a",
                "    documented incident (AGENTS.md section 5). For a frozen host the shipper is",
                "    SUPPOSED to be stopped: its BYTES still arrive because the AUTHORITY pulls",
                "    them, and only the PARSED projection stops. Fill that from the authority --",
                "    it is ledger item 561 -- as:",
                "      DSH_HOME=<the staged sessions> DSH_ARCHIVE_MACHINE=<host> \\\\",
                "        node scripts/push-dsh-sessions.mjs --all",
                "    under a memory ceiling, because the dry run measured 216,738 rows.",'''

src = io.open(P, encoding="utf-8").read()
if "FIRST ASK WHETHER THE MACHINE IS FROZEN" in src:
    print("ALREADY-PATCHED: nothing written")
    sys.exit(0)
n = src.count(OLD)
if n != 1:
    print("REFUSED: anchor found %d times (expected 1)" % n)
    sys.exit(2)
out = src.replace(OLD, NEW, 1)
try:
    ast.parse(out)
except SyntaxError as exc:
    print("REFUSED: would not parse: %s" % exc)
    sys.exit(3)
io.open(P, "w", encoding="utf-8").write(out)
print("WROTE %s  %d -> %d chars" % (P, len(src), len(out)))
