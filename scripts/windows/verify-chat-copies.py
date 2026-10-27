#!/usr/bin/env python3
"""Verify every file in car_chat_hits against a live VS Code chat copy.

For each file: if no live file shares its exact byte length it cannot be a duplicate -> UNIQUE.
Otherwise SHA-256 both sides and compare. Writes one line per file: verdict<TAB>size<TAB>path<TAB>match
"""
import hashlib, os, sys, json

SRC = r"C:\Users\ezabz\car_chat_hits"
LIVE_ROOTS = [
    r"C:\Users\ezabz\AppData\Roaming\Code",
    r"C:\Users\ezabz\AppData\Local\PersonalSecretaryVSCode",
    r"C:\Users\ezabz\AppData\Local\CleanCopilotVSCode",
    r"C:\Users\ezabz\.copilot",
]
OUT = r"C:\Users\ezabz\Code\_audit\car_chat_verify.tsv"

def sha(p, buf=4 << 20):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while True:
            b = f.read(buf)
            if not b:
                break
            h.update(b)
    return h.hexdigest()

# index live copies by size
index = {}
n = 0
for root in LIVE_ROOTS:
    if not os.path.isdir(root):
        continue
    for dp, dn, fn in os.walk(root):
        for f in fn:
            if not f.lower().endswith(".jsonl"):
                continue
            p = os.path.join(dp, f)
            try:
                st = os.stat(p)
            except OSError:
                continue
            index.setdefault(st.st_size, []).append(p)
            n += 1
print("live jsonl indexed: %d files, %d distinct sizes" % (n, len(index)), flush=True)

files = sorted(os.listdir(SRC))
rows = []
dups = []
for i, name in enumerate(files, 1):
    p = os.path.join(SRC, name)
    if not os.path.isfile(p):
        continue
    st = os.stat(p)
    cands = index.get(st.st_size)
    verdict, match = "UNIQUE", ""
    if cands:
        h = sha(p)
        for c in cands:
            if sha(c) == h:
                verdict, match = "DUPLICATE", c
                break
    rows.append((verdict, st.st_size, p, match))
    if verdict == "DUPLICATE":
        dups.append(p)
    if i % 50 == 0:
        print("  %d/%d checked, %d duplicates" % (i, len(files), len(dups)), flush=True)

with open(OUT, "w", encoding="utf-8") as f:
    for v, s, p, m in rows:
        f.write("%s\t%d\t%s\t%s\n" % (v, s, p, m))

dsz = sum(os.path.getsize(p) for p in dups)
print("VERDICT: %d duplicate (%.2f GiB), %d unique (%.2f GiB)"
      % (len(dups), dsz / 2**30, len(rows) - len(dups),
         (sum(r[1] for r in rows) - dsz) / 2**30))
