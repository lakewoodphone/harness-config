#!/usr/bin/env python3
"""Final verification: nothing lost, nothing colliding, nothing inside another host's window."""
import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path

repo = Path(r"C:\Users\ezabz\code\harness-config")
spec = importlib.util.spec_from_file_location("jl", repo / "journal" / "tools" / "journal.py")
jl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(jl)
jl.JOURNAL = repo / "journal"
jl.clear_caches()
ME = jl.host_tag().upper()


def sha(b):
    return hashlib.sha256(b).hexdigest()


def body_of(path, kind):
    return sha(jl.parse_entry(path, kind)["body"].encode("utf-8"))


m1 = json.loads((repo / "docs" / "mesh" / "163-repair-manifest.json").read_text())
m2 = json.loads((repo / "docs" / "mesh" / "163-repair-pass2-manifest.json").read_text())
moved2 = {f["pass1_id"]: f for f in m2["moved"]}
rows = jl.read_ledger_rows()

ok = True
final = []
for rec in m1["renumbered"]:
    kind, orig = rec["kind"], rec["old_id"]
    orig_path = repo / "journal" / rec["archive"]
    if not orig_path.exists():
        print("MISSING archive original %s" % orig_path)
        ok = False
        continue
    ob = body_of(orig_path, kind)
    if ob != rec["body_sha256"]:
        print("ARCHIVE BODY MISMATCH %s" % orig)
        ok = False
    if rec["new_id"] in moved2:
        f = moved2[rec["new_id"]]
        cur_path, cur_id = repo / "journal" / f["path"], f["id"]
    else:
        cur_path, cur_id = repo / "journal" / rec["new_file"], rec["new_id"]
    if not cur_path.exists():
        print("MISSING final %s" % cur_path)
        ok = False
        continue
    fb = body_of(cur_path, kind)
    if fb != rec["body_sha256"]:
        print("FINAL BODY MISMATCH %s -> %s" % (orig, cur_id))
        ok = False
    cov = [r for r in rows if r["kind"] == kind and r["host"].upper() != ME
           and r.get("reserved_from", 0) <= jl.num_of(cur_id) <= r["reserved_through"]]
    if cov:
        print("FINAL ID IN FOREIGN WINDOW %s: %s" % (cur_id, cov))
        ok = False
    final.append((orig, rec["new_id"], cur_id, cur_path))

print("renumbered originals checked : %d" % len(final))
print("byte-identical duplicates    : %d (archived to archive/duplicates/)" % len(m1["duplicates"]))
print("original file bodies equal   : %s" % ok)

# every untracked entry that overlapped origin/main is gone
st = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all"],
                    cwd=str(repo), capture_output=True).stdout.decode("utf-8", "replace")
unt = [l[3:].strip() for l in st.splitlines() if l.startswith("??")]
up_all = set(subprocess.run(["git", "ls-tree", "-r", "--name-only", "origin/main"],
                            cwd=str(repo), capture_output=True).stdout.decode().split())
print("untracked checkout blockers (any path origin/main wants): %d"
      % len([p for p in unt if p in up_all]))

# the 63 archive originals + 235 untracked entries
for d in ("journal/archive/collided-ids-2026-10-11", "journal/archive/duplicates"):
    n = sum(1 for _ in (repo / d).rglob("*.md"))
    print("%-48s %d .md" % (d, n))
print("entries/ .md files: %d" % len(list((repo / "journal" / "entries").rglob("*.md"))))

# alias chain for one entry, as a reader would follow it
print("\nalias chain sample (D3032): D3032 -> %s -> %s"
      % (m1["renumbered"][0]["new_id"], moved2.get(m1["renumbered"][0]["new_id"], {}).get("id")))
al = (repo / "journal" / "index" / "aliases.tsv").read_text(encoding="utf-8", errors="replace")
for tgt in ("D3032", "D3111"):
    for line in al.splitlines():
        if line.startswith(tgt + "\t"):
            print("   %s" % line[:120])
