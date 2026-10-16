#!/usr/bin/env python3
"""30-merge.py -- build the CROSS-TREE UNION of five journal trees at /root/work/r7/merged-journal.

READ-ONLY ON EVERY SOURCE. Every source file is opened with read_bytes() and nothing
under trees/ is created, moved or deleted by this script.

Why the overlay is not a plain `cp -r` and not a plain "add only new ids":

  * In every one of the five trees the entry file's stem EQUALS the id in its first-line
    marker (measured: 0 exceptions in 17387 files) and no id is carried by two files.
  * `journal.py verify` REQUIRES that (see tools/verify.py: `marker id != file name` is a
    FAIL), and `check`/`verify` are the gates this job must pass.
  * Therefore two trees holding id X with DIFFERENT bodies cannot both be laid down at
    `entries/<kind>/X.md` -- one overwrites the other, and the overwritten body is gone.
  * So a colliding body is laid down under the historical second-copy name
    `<X>b.md`, `<X>c.md`, ... (the same convention `repair-ids` documents for
    `entries/lessons/L1999b.md`). The MARKER INSIDE IS LEFT UNCHANGED, so the merged tree
    temporarily carries the same id in two files -- which is exactly the input
    `journal.py repair-ids` is written to renumber, and exactly the state its own comment
    describes having been measured on.

A body already present in the union for that id is SKIPPED (it is the same entry; copying
it again would only create work for `dedupe`). A body present under a DIFFERENT id is
copied, because `dedupe` exists to collapse that case and it must be able to see it.

Nothing is deleted and nothing is overwritten: `free_path()` never returns an existing path.
"""
from __future__ import annotations

import collections
import hashlib
import pathlib
import re
import shutil
import sys
import time

R7 = pathlib.Path("/root/work/r7")
TREES = R7 / "trees"
DEST = R7 / "merged-journal"
BASE = "yoga"
ORDER = ["yoga", "cloud", "tech", "linux", "mac"]
KINDS = ("decisions", "handoff", "lessons", "pain", "wins")
MARKER = re.compile(r"^<!--\s*e:(?P<kind>[a-z]+)\|(?P<id>[^|]*)\|")


def marker_id(raw: bytes) -> str:
    m = MARKER.match(raw.decode("utf-8", "replace").split("\n")[0])
    if not m:
        raise SystemExit("no marker on first line")
    return m.group("id")


def free_path(d: pathlib.Path, stem: str) -> pathlib.Path:
    """<stem>.md, else <stem>b.md, <stem>c.md ... -- NEVER an existing path."""
    p = d / (stem + ".md")
    if not p.exists():
        return p
    n = 0
    while True:
        n += 1
        letters = []
        x = n
        while True:
            x, r = divmod(x - 1, 26)
            letters.append(chr(ord("b") + r))
            if x == 0:
                break
        p = d / (stem + "".join(reversed(letters)) + ".md")
        if not p.exists():
            return p


def main() -> int:
    for t in ORDER:
        if not (TREES / t / "journal" / "entries").is_dir():
            raise SystemExit("missing tree %s" % t)
    if DEST.exists():
        aside = DEST.with_name(DEST.name + ".prev-" + time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()))
        DEST.rename(aside)
        print("existing %s moved aside to %s (not deleted)" % (DEST, aside))

    shutil.copytree(TREES / BASE / "journal", DEST, symlinks=True)
    print("base = %s  -> %s" % (BASE, DEST))
    df = shutil.disk_usage(str(DEST))
    print("disk at start: total=%.1fGB used=%.1fGB free=%.1fGB" % (df.total / 2**30, df.used / 2**30, df.free / 2**30))

    have = collections.defaultdict(set)          # marker id -> {sha256 already present}
    stats = collections.Counter()
    per_tree_added = collections.Counter()
    per_tree_skipped = collections.Counter()
    for kind in KINDS:
        d = DEST / "entries" / kind
        if not d.is_dir():
            continue
        for p in sorted(d.glob("*.md")):
            raw = p.read_bytes()
            have[marker_id(raw)].add(hashlib.sha256(raw).hexdigest())
            stats["base_files"] += 1
    print("base files: %d  distinct ids: %d" % (stats["base_files"], len(have)))

    for t in ORDER[1:]:
        src = TREES / t / "journal" / "entries"
        for kind in KINDS:
            d = src / kind
            if not d.is_dir():
                continue
            for p in sorted(d.glob("*.md")):
                raw = p.read_bytes()
                sha = hashlib.sha256(raw).hexdigest()
                i = marker_id(raw)
                if sha in have[i]:
                    stats["skipped_same_body"] += 1
                    per_tree_skipped[t] += 1
                    continue
                dest = free_path(DEST / "entries" / kind, p.stem)
                dest.write_bytes(raw)                 # verbatim; the marker is untouched
                have[i].add(sha)
                stats["added"] += 1
                per_tree_added[t] += 1
                if dest.stem != p.stem:
                    stats["added_suffixed"] += 1
                    if stats["added_suffixed"] <= 8:
                        print("  suffixed: %s/%s -> %s (id stays %s)"
                              % (t, p.name, dest.name, i))
                else:
                    stats["added_plain"] += 1
        print("overlaid %-8s added=%d skipped_same_body=%d"
              % (t, per_tree_added[t], per_tree_skipped[t]))

    n_files = sum(len(list((DEST / "entries" / k).glob("*.md"))) for k in KINDS)
    multi = {i: len(s) for i, s in have.items() if len(s) > 1}
    body_dup = sum(len(s) for s in have.values())
    print("")
    print("MERGED entry files            %d" % n_files)
    print("MERGED distinct ids           %d" % len(have))
    print("MERGED (id,body) pairs        %d" % body_dup)
    print("ids carried by >1 body        %d  (sum of extra bodies = %d)"
          % (len(multi), sum(v - 1 for v in multi.values())))
    print("added=%d (plain=%d suffixed=%d) skipped_same_body=%d"
          % (stats["added"], stats["added_plain"], stats["added_suffixed"], stats["skipped_same_body"]))
    df = shutil.disk_usage(str(DEST))
    print("disk at end:   used=%.1fGB free=%.1fGB" % (df.used / 2**30, df.free / 2**30))
    print("merged tree bytes: %d" % sum(
        p.stat().st_size for p in DEST.rglob("*") if p.is_file()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
