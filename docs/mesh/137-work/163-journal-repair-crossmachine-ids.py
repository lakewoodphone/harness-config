#!/usr/bin/env python3
"""Repair cross-machine duplicate-id collisions in this journal checkout.

WHY THIS EXISTS (measured 2026-10-11 on ZABZ-TECH):
  `journal.py repair-ids` cannot see this defect. Its loader, `load_entries()`, reads
  `entries/` only, so within one checkout each id maps to exactly one file and it prints
  "no id collides with different content -- nothing to do". The collision is between a
  LOCAL UNTRACKED entry and a DIFFERENT entry at the SAME PATH on `origin/main`. Nothing
  in `repair-ids` or `dedupe` looks at a git ref, so neither can be pointed at it.

WHAT IT DOES:
  Replicates `cmd_repair_ids`' per-duplicate body VERBATIM -- parse_entry -> rewrite the
  id in the heading -> entry_bytes -> atomic_write -> shutil.move the original into
  `archive/collided-ids-<today>/<kind>/` -> record_alias -- with two deliberate changes:

  1. `keep` is FORCED to the published (origin/main) copy instead of being chosen by
     earliest date. The resolution rule is "the published copy keeps the id; the local
     unpublished copy is renumbered", and other machines' refs already cite the published
     id. repair-ids sorts by date and would sometimes keep the local copy instead.
  2. The new id is allocated against EVERY git ref, not just `entries/`. `_next_free()`
     is fed a `taken` set seeded with every id visible on `origin/main`, and the number
     is passed through the journal's own `ensure_reservation()` so a mint outside this
     host's reserved window is refused rather than performed.

  Byte-identical files (same path, same bytes on origin/main) are handled the way
  `cmd_dedupe` handles an identity duplicate: moved to `archive/duplicates/<kind>/` with
  `record_alias(id, kind, id, ...)` -- the published copy keeps the id and the path.

  The whole pass runs under the journal's own `acquire_lock()`, the way every
  BLANKET_LOCK_COMMAND does, so a concurrent `journal.py append` defers (exit 5, nothing
  written) instead of writing into a tree that is being renumbered.

HARD GATES (a failure stops before anything is written for that entry):
  * entry_bytes(parse_entry(f)) must equal the file's bytes exactly (round-trip fidelity);
  * the new heading must be the old heading with exactly one id-token substitution;
  * the renumbered file, re-parsed, must carry the identical body.

Usage:  python 163-journal-repair-crossmachine-ids.py [--apply] [--repo PATH]
Without --apply it is a report only.
"""
import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

STAMP = "20261011T2245Z"


def load_journal(repo: Path):
    jp = repo / "journal" / "tools" / "journal.py"
    spec = importlib.util.spec_from_file_location("journal_mod", jp)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def git(repo: Path, *a):
    p = subprocess.run(["git", "-c", "core.quotepath=false"] + list(a), cwd=str(repo),
                       capture_output=True)
    return p.stdout


def blobsha(data: bytes) -> str:
    h = hashlib.sha1()
    h.update(b"blob %d\0" % len(data))
    h.update(data)
    return h.hexdigest()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=r"C:\Users\ezabz\code\harness-config")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--manifest", default="")
    args = ap.parse_args()
    repo = Path(args.repo)
    jl = load_journal(repo)
    jl.JOURNAL = repo / "journal"
    jl.clear_caches()

    # ---- 1. the collision set, measured from the ref --------------------------------
    st = git(repo, "status", "--porcelain", "--untracked-files=all", "--", "journal/entries")
    untracked = [l[3:].strip() for l in st.decode("utf-8", "replace").splitlines()
                 if l.startswith("??")]
    up = {}
    for line in git(repo, "ls-tree", "-r", "origin/main", "journal/entries").decode(
            "utf-8", "replace").splitlines():
        if not line.strip():
            continue
        meta, path = line.split("\t", 1)
        up[path] = meta.split()[2]
    overlap = sorted(p for p in untracked if p in up)
    different, identical = [], []
    for p in overlap:
        b = (repo / p).read_bytes()
        (identical if blobsha(b) == up[p] else different).append(p)

    # REPO-WIDE pre-flight. `git checkout` refuses to write over ANY untracked file, including
    # ones byte-identical to the blob, so a blocker anywhere blocks the rebase -- not only in
    # journal/entries. Entries are the only place this repair writes, so anything else found
    # here is reported and left alone.
    all_untracked = [l[3:].strip() for l in
                     git(repo, "status", "--porcelain", "--untracked-files=all")
                     .decode("utf-8", "replace").splitlines() if l.startswith("??")]
    up_all = set(git(repo, "ls-tree", "-r", "--name-only", "origin/main")
                 .decode("utf-8", "replace").split())
    outside = sorted(p for p in all_untracked if p in up_all and not p.startswith("journal/entries/"))

    print("untracked entry files : %d" % len(untracked))
    print("also on origin/main   : %d" % len(overlap))
    print("  different body      : %d" % len(different))
    print("  byte-identical      : %d" % len(identical))
    print("checkout blockers OUTSIDE journal/entries/: %d" % len(outside))
    for p in outside:
        print("  BLOCKER %s" % p)
    print()
    for p in identical:
        print("IDENTICAL   %s" % p)
    print()

    # ---- 2. the lock ----------------------------------------------------------------
    if not args.apply:
        for p in different:
            kind = p.split("/")[-2]
            e = jl.parse_entry(repo / p, kind)
            print("WOULD RENUMBER %-44s %s (host=%s date=%s)" % (p, e["id_full"], e.get("host"), e.get("date")))
        print("\nreport only; re-run with --apply")
        return 0

    acquired, token = jl.acquire_lock("repair-ids")
    if not acquired:
        print("REFUSED: another session holds the journal lock (%s). Nothing written."
              % jl._read_lock_text(jl.JOURNAL / jl.LOCK_NAME))
        return 3
    manifest = {"stamp": STAMP, "renumbered": [], "duplicates": [], "refused": []}
    try:
        # every id visible on origin/main, as filenames (the filename IS the id)
        taken = set()
        for path in up:
            taken.add(Path(path).stem)
        local_entries, _p = jl.load_entries()
        for e in local_entries:
            taken.add(e["id_full"])
        kinds = sorted({p.split("/")[-2] for p in different})
        ceilings = {}
        for k in kinds:
            ceilings[k] = max(jl.max_number(k), jl.allocation_ceiling(k),
                              jl.git_max(k, fetch=True)[0])
            print("ceiling %-10s %s%d" % (k, jl.KINDS[k]["letter"], ceilings[k]))

        # ---- 3. renumber the 47 -----------------------------------------------------
        for p in different:
            kind = p.split("/")[-2]
            path = repo / p
            full = jl.parse_entry(path, kind)
            old_id = full["id_full"]
            otxt = path.read_bytes()
            if jl.entry_bytes(full).encode("utf-8") != otxt:
                print("REFUSING %s: entry_bytes() does not round-trip this file; a rewrite "
                      "could lose bytes. Left untouched." % p)
                manifest["refused"].append({"path": p, "id": old_id, "why": "no round-trip"})
                continue
            # allocate: journal's own ceiling + this host's reservation
            cand = max(ceilings[kind], jl.next_writable(kind) - 1, jl._local_kind_top(kind)) + 1
            ok, want, detail = jl.ensure_reservation(kind, cand, fetch=False)
            if not ok:
                print("REFUSING %s: %s" % (old_id, detail))
                manifest["refused"].append({"path": p, "id": old_id, "why": detail})
                continue
            n = max(cand, want)
            while True:
                new_id = "%s%d" % (jl.KINDS[kind]["letter"], n)
                if new_id not in taken and not (jl.entries_dir() / kind / (new_id + ".md")).exists():
                    break
                n += 1
            taken.add(new_id)
            ceilings[kind] = max(ceilings[kind], n)
            # `handoff` headings carry no id (`## <stamp> · <host> · <title>`): the id lives
            # only in the marker line. Every other kind carries it in the heading too.
            # cmd_repair_ids substitutes in the heading and leaves it alone when the id is
            # absent, which is correct; requiring the id to be present was my error.
            new_heading = re.sub(r"\b" + re.escape(old_id) + r"\b", new_id, full["heading"], count=1)
            oh, nh = full["heading"].encode("utf-8"), new_heading.encode("utf-8")
            if old_id.encode() in oh:
                if nh != oh.replace(old_id.encode(), new_id.encode(), 1):
                    print("REFUSING %s: heading rewrite is not a single token substitution." % old_id)
                    manifest["refused"].append({"path": p, "id": old_id, "why": "heading rewrite"})
                    continue
            elif nh != oh:
                print("REFUSING %s: heading changed although the id is not in it." % old_id)
                manifest["refused"].append({"path": p, "id": old_id, "why": "heading changed"})
                continue
            full2 = dict(full)
            full2["id_full"] = new_id
            full2["heading"] = new_heading
            full2["sha"] = jl.entry_hash(new_heading, full["body"])
            ntxt = jl.entry_bytes(full2).encode("utf-8")
            # PROOF THAT ONLY THE ID AND THE CONTENT HASH MOVED. Three token substitutions
            # are the ONLY legal difference between the two files:
            #   1. the id in the first line, `<!-- e:<kind>|<ID>|... -->`;
            #   2. the id in the heading, for the kinds whose heading carries it;
            #   3. the `sha=` field of the trailing j2 meta line, which is
            #      entry_hash(heading, body) and therefore MUST change when the heading does.
            # The body is not a permitted difference, and is checked again after the write.
            old_sha = jl.entry_hash(jl.effective_heading(full), full["body"]).encode()
            new_sha = jl.entry_hash(jl.effective_heading(full2), full["body"]).encode()
            marker_old = otxt.split(b"\n", 1)[0]
            marker_new = marker_old.replace(old_id.encode(), new_id.encode(), 1)
            expect = otxt
            if marker_new != marker_old:
                expect = expect.replace(marker_old, marker_new, 1)
            if nh != oh:
                expect = expect.replace(oh, nh, 1)
            if new_sha != old_sha:
                expect = expect.replace(old_sha, new_sha, 1)
            if ntxt != expect:
                print("REFUSING %s: the new bytes differ from the old by more than the id token "
                      "and the content hash." % old_id)
                manifest["refused"].append({"path": p, "id": old_id, "why": "byte delta"})
                continue
            dest = jl.entries_dir() / kind / (new_id + ".md")
            archive = jl.JOURNAL / jl.ARCHIVE_NAME / ("collided-ids-" + jl.today()) / kind
            archive.mkdir(parents=True, exist_ok=True)
            adest = archive / (old_id + ".md")
            k = 1
            while adest.exists():
                k += 1
                adest = archive / ("%s-%d.md" % (old_id, k))
            jl.atomic_write(dest, jl.entry_bytes(full2))
            shutil.move(str(path), str(adest))
            back = jl.parse_entry(dest, kind)
            if back["body"] != full["body"]:
                print("FATAL: body changed for %s -> %s" % (old_id, new_id))
                return 9
            jl.record_alias(old_id, kind, new_id,
                            "cross-machine id collision: origin/main keeps %s at %s; this "
                            "checkout's unpublished copy renumbered" % (old_id, p),
                            host=full.get("host"), sha=full.get("hash"),
                            source=jl._rel_of(adest))
            manifest["renumbered"].append({
                "kind": kind, "old_id": old_id, "new_id": new_id, "src": p,
                "new_file": jl._rel_of(dest), "archive": jl._rel_of(adest),
                "date": full.get("date"), "host": full.get("host"),
                "bytes": len(otxt), "sha256_before": sha256(otxt), "sha256_after": sha256(ntxt),
                "body_sha256": sha256(full["body"].encode("utf-8")),
                "heading_before": full["heading"], "heading_after": new_heading,
            })
            print("renumbered %-8s -> %-8s  %s -> %s" % (old_id, new_id, p, jl._rel_of(dest)))

        # ---- 4. the byte-identical duplicates ---------------------------------------
        for p in identical:
            kind = p.split("/")[-2]
            path = repo / p
            full = jl.parse_entry(path, kind)
            dest = jl.JOURNAL / jl.ARCHIVE_NAME / "duplicates" / kind / (full["id_full"] + ".md")
            dest.parent.mkdir(parents=True, exist_ok=True)
            k = 1
            while dest.exists():
                k += 1
                dest = jl.JOURNAL / jl.ARCHIVE_NAME / "duplicates" / kind / ("%s-%d.md" % (full["id_full"], k))
            shutil.move(str(path), str(dest))
            jl.record_alias(full["id_full"], kind, full["id_full"],
                            "byte-identical to the published copy on origin/main; the published "
                            "copy keeps the id and the path", host=full.get("host"),
                            sha=full.get("hash"), source=jl._rel_of(dest))
            manifest["duplicates"].append({"kind": kind, "id": full["id_full"], "src": p,
                                           "archive": jl._rel_of(dest)})
            print("duplicate   %-8s archived  %s" % (full["id_full"], jl._rel_of(dest)))
    finally:
        jl.release_lock(token)

    jl.rebuild_cache(compute_drift=True)
    print("\n-- %d renumbered, %d duplicates archived, %d refused"
          % (len(manifest["renumbered"]), len(manifest["duplicates"]), len(manifest["refused"])))
    if args.manifest:
        Path(args.manifest).write_text(json.dumps(manifest, indent=1), encoding="utf-8")
        print("manifest: %s" % args.manifest)
    return 0 if not manifest["refused"] else 4


if __name__ == "__main__":
    raise SystemExit(main())
