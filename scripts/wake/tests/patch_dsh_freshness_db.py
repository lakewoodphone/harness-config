#!/usr/bin/env python3
"""Point the archive-staleness checker at the database that actually holds dsh_sessions.

MEASURED 2026-10-18 on the authority. `check-dsh-freshness.py` defaulted
`DSH_ARCHIVE_DB` to `/home/zabz/personal-secretary-mvp/data/secretary.db`, a 1.9 MB file that
does NOT contain `dsh_sessions`. Every run therefore reported, inside dormant-handoff:

    archive-check UNUSABLE (Unreadable: freshness checker refused (its inputs could not be
    read): {"error": "could not read dsh_sessions: no such table: dsh_sessions"})

while the live table held 8,415 rows in `/root/authority.db` on the same host.

This is the fifth wrong-store default in this class (_flag.app_db, cron-targets, dormant-handoff's
repo path, loop-stall's missing detector) and it is the worst of them, because this is the check
that guards whether session archives still have a copy -- AGENTS.md section 1. The original path
is kept as the fallback so a non-authority host behaves exactly as before, and an explicit
DSH_ARCHIVE_DB still wins.
"""
import ast
import io
import sys

P = "/opt/company/scripts/server/check-dsh-freshness.py"

OLD = '''ARCHIVE = os.environ.get(
    "DSH_ARCHIVE_DB", "/home/zabz/personal-secretary-mvp/data/secretary.db")'''

NEW = '''# MEASURED 2026-10-18: this default pointed at a 1.9 MB copy that does NOT hold
# `dsh_sessions`, so every dormant-handoff run reported
#   archive-check UNUSABLE ... "could not read dsh_sessions: no such table"
# while the live table (8,415 rows) sat in /root/authority.db on this same host. Fifth
# wrong-store default found in this class, and the one guarding the archive that AGENTS.md
# section 1 says must always have a copy. Same precedent as _flag.app_db: prefer the
# authority when it exists; keep the old path as the fallback; an explicit env still wins.
ARCHIVE = os.environ.get("DSH_ARCHIVE_DB") or (
    "/root/authority.db" if os.path.exists("/root/authority.db")
    else "/home/zabz/personal-secretary-mvp/data/secretary.db")'''

src = io.open(P, encoding="utf-8").read()
if "fifth wrong-store default" in src:
    print("ALREADY-PATCHED: nothing written")
    sys.exit(0)
if src.count(OLD) != 1:
    print("REFUSED: anchor found %d times" % src.count(OLD))
    sys.exit(2)
out = src.replace(OLD, NEW, 1)
try:
    ast.parse(out)
except SyntaxError as exc:
    print("REFUSED: would not parse: %s" % exc)
    sys.exit(3)
io.open(P, "w", encoding="utf-8").write(out)
print("WROTE %s  %d -> %d chars" % (P, len(src), len(out)))
