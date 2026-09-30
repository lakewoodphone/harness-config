#!/usr/bin/env python3
"""Give work-integrator.py a per-run limit, so scheduling it cannot bury the ledger.

MEASURED 2026-09-30, cold dry run on the authority: 12 unmerged branches for kosher-ai-filter, 9 for
lpt-website, 5 for lpt-sync, and the same shape for cfo, personality-system, chumash and prod-db-sync. The
script already filters noise ref classes and dedupes by title, but it has only --days and --project, so one
scheduled run files every candidate at once. The 2026-09-28 design recorded the same failure by another
route - "27 work orders that will never run" - and the script's own header says "a backlog nobody can read
is worse than filing none".

After this patch: `--limit N`, default 3, counted across all projects in one run, and reported per branch so
a deferred candidate is visible rather than silent.

Fails closed: every anchor must appear exactly once or nothing is written.
"""
import os
import shutil
import sys
import time

TARGET = sys.argv[1] if len(sys.argv) > 1 else "/home/zabz/bin/work-integrator.py"

PAIRS = [
    # 1. the new argument
    ('    ap.add_argument("--json", action="store_true")',
     '    ap.add_argument("--json", action="store_true")\n'
     '    ap.add_argument("--limit", type=int, default=3,\n'
     '                    help="file at most N integration items in one run (default 3). A backlog nobody "\n'
     '                         "can read is worse than filing none - cold dry run 2026-09-30 found 12 "\n'
     '                         "unmerged branches for kosher-ai-filter, 9 for lpt-website, 5 for lpt-sync.")'),
    # 2. the counter, outside the project loop so the limit is per RUN, not per project
    ('    for row in doc.get("projects", []):',
     '    filed_run = 0\n'
     '    for row in doc.get("projects", []):'),
    # 3. the gate, first thing in the per-branch loop
    ('        for ref, age in sorted(recent):',
     '        for ref, age in sorted(recent):\n'
     '            if filed_run >= a.limit:\n'
     '                filed.append({"branch": ref, "age_days": age, "item": "deferred (per-run limit)"})\n'
     '                continue'),
    # 4. count what a dry run WOULD file, so the bound is visible before anything is written
    ('            if a.dry_run:\n'
     '                filed.append({"branch": ref, "age_days": age, "item": "would-file"})\n'
     '                continue',
     '            if a.dry_run:\n'
     '                filed_run += 1\n'
     '                filed.append({"branch": ref, "age_days": age, "item": "would-file"})\n'
     '                continue'),
    # 5. count a real filing
    ('            if "item-filed" in (out2 or "") and m:',
     '            if "item-filed" in (out2 or "") and m:\n'
     '                filed_run += 1'),
]

src = open(TARGET, encoding="utf-8").read()
if "filed_run" in src:
    sys.exit("SKIP: already patched (filed_run present)")
for old, _ in PAIRS:
    n = src.count(old)
    if n != 1:
        sys.exit("FAIL: anchor found %d times, expected exactly 1:\n%s\n- nothing written" % (n, old[:120]))
for old, new in PAIRS:
    src = src.replace(old, new, 1)

stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
backup = "%s.bak-perrun-limit-%s" % (TARGET, stamp)
shutil.copy2(TARGET, backup)
tmp = TARGET + ".tmpnew"
with open(tmp, "w", encoding="utf-8") as fh:
    fh.write(src)
os.chmod(tmp, os.stat(TARGET).st_mode)
os.replace(tmp, TARGET)
print("patched %s -> backup %s (%d replacements)" % (TARGET, backup, len(PAIRS)))
