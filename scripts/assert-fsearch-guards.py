"""Assert every executable `tri` reference sits inside a `trigram` guard.

This is the check I should have run when I made the trigram index optional. Fixing
them as they surface is how the same class of bug ships twice; asserting the
invariant is how it stops.
"""
import io
import re
import sys

P = r"C:\Users\ezabz\Code\_scratch\pull-20260911\fsearch.py"
lines = io.open(P, encoding="utf-8").read().split("\n")

ref = re.compile(r'(?:FROM|INTO|UPDATE)\s+tri\b|\btri\s*\(|\bMATCH\b[^\n]*\btri\b')
GUARDS = ("if trigram", "have_tri", 'fts_exists("tri")', "trigram and")
problems = []
for i, l in enumerate(lines):
    st = l.strip()
    if st.startswith("#") or st.startswith("*"):
        continue
    if not ref.search(st):
        continue
    # Walk back to the top of the enclosing function and look for a guard.
    guarded = False
    for j in range(i - 1, -1, -1):
        prev = lines[j]
        if prev.startswith("def ") or prev.startswith("class "):
            break
        if any(g in prev for g in GUARDS):
            guarded = True
            break
    tag = "GUARDED " if guarded else "UNGUARDED"
    print(f"  {tag} line {i+1}: {st[:88]}")
    if not guarded:
        problems.append(i + 1)

print()
if problems:
    print(f"FAIL: {len(problems)} unguarded tri reference(s): {problems}")
    sys.exit(1)
print("PASS: every executable tri reference is behind a trigram guard")
