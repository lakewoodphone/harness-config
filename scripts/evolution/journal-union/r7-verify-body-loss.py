#!/usr/bin/env python3
"""r7-verify-body-loss.py — did the journal union lose an entry? Compare BODIES, not files.

WHY THE PREVIOUS TWO TESTS WERE BOTH WRONG, because the shape of the mistake is the point.

Test 1 was in the round-6 brief: "the count of ids whose body differs from the merged tree must be 0".
**Structurally impossible** -- an id holds exactly one body, so after a union the losers are renamed
to fresh ids and the count of ids that USED to carry more than one body does not change. The builder
refused to report 0 and said so.

Test 2 was mine, written on ZABZ-YOGA: compare the multiset of whole-file sha256 values between the
five source manifests and the merged manifest. It reported **403 bodies missing and 377 invented** --
and that number is an ARTEFACT, not a loss. Every entry file begins with a header line carrying its own
id:

    <!-- e:decisions|D3036|2026-10-14 23:29 UTC|ZABZ-YOGA|open -->

so renumbering an entry changes the file's bytes while the BODY is untouched. The merged tree
renumbered 376 entries; the "missing/invented" counts sit right where those renumberings are. A whole-
file hash is not a body identity when the id lives inside the file.

WHAT THIS DOES INSTEAD: derive a BODY SIGNATURE -- the file with its `<!-- e:... -->` header line and
any trailing `<!-- j2 ... -->` metadata line removed -- and compare the two multisets of signatures.
That is the honest question: **is every distinct body present, regardless of which id carries it?**

Usage (run where the trees are):
    python3 r7-verify-body-loss.py --trees /root/work/r7/trees --merged /root/work/r7/merged-journal
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import pathlib
import re
import sys

HEADER = "<!-- e:"
META = "<!-- j2"


def body_sig(p: pathlib.Path, normalise_ids: bool = False) -> str:
    """The entry's body: the file minus its id-bearing header and its trailing metadata line.

    `normalise_ids` additionally replaces every whole-word occurrence of the entry's OWN id with
    `<ID>`. That matters because several entry kinds carry their id in the body as well -- a lesson
    opens `**L3774 - ...` -- so a renumber changes the body's bytes even though the entry is the same
    one. Without this the test reports every renumbered entry as one body lost and one body invented,
    which is a pairing that looks like data loss and is not.
    """
    lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    while lines and lines[0].startswith(HEADER):
        lines.pop(0)
    while lines and lines[-1].strip().startswith(META):
        lines.pop()
    text = "\n".join(ln.rstrip() for ln in lines).strip()
    if normalise_ids and p.stem:
        # Normalise EVERY id-shaped token, not just the file's own stem. Two reasons, both measured:
        #   * the merge renamed into `<ID>b.md` suffixes, so a file's stem is `H3401b` while its body
        #     still says `H3401` -- asking only for the stem leaves the body's id in place;
        #   * a renumbered entry's text cites OTHER ids (a lesson heading names the handoff it
        #     corrects), so two copies of the same entry can differ by a citation the merge rewrote.
        # Asking only for the stem produced 11 phantom "missing" bodies and 4 phantom "invented" ones.
        text = re.sub(r"\b[DHILPW][0-9]{1,6}[a-z]{0,3}\b", "<ID>", text)
        text = re.sub(r"\b" + re.escape(p.stem) + r"\b", "<ID>", text)
        # COLLAPSE WHITESPACE. A renumbering passes the entry through the journal's own writer, which
        # RE-WRAPS the paragraph: the words and their order are identical and every line break moves.
        # Comparing line-by-line therefore reported nine complete entries as lost -- and a diff of one
        # of them showed only line-wrap churn. The question this test asks is "is this content here",
        # and content does not live in line breaks.
        text = " ".join(text.split())
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def collect(root: pathlib.Path, normalise_ids: bool = False, include_archive: bool = False) -> dict[str, list[str]]:
    """body signature -> the ids carrying it. Retired copies are excluded.

    `journal/archive/duplicates/` holds files `journal.py dedupe` MOVED there on purpose -- retired
    copies, not live entries. The first run of this test globbed them in and reported them as bodies
    the union had lost: H2781, H458 and P2561bc in the cloud tree all sat under
    `archive/duplicates/`. That is a test fault wearing the shape of a data-loss finding.
    """
    out: dict[str, list[str]] = collections.defaultdict(list)
    skipped = 0
    for f in sorted(root.rglob("*.md")):
        if not include_archive and "/archive/" in str(f).replace("\\", "/"):
            skipped += 1
            continue
        out[body_sig(f, normalise_ids)].append(f.stem)
    if skipped:
        print(f"                 ({skipped} file(s) under archive/ skipped -- retired copies)")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trees", required=True, help="directory holding one subdir per source tree")
    ap.add_argument("--merged", required=True)
    ap.add_argument("--show", type=int, default=12)
    ap.add_argument("--include-archive", action="store_true",
                    help="count files under archive/ too -- journal.py dedupe MOVES exact duplicates there")
    ap.add_argument("--normalise-ids", action="store_true",
                    help="strip each entry's own id from its body before hashing -- see body_sig")
    args = ap.parse_args()

    trees = pathlib.Path(args.trees)
    merged_root = pathlib.Path(args.merged)
    if not trees.is_dir():
        print(f"! {trees} not found -- the collected source trees are not on this host", file=sys.stderr)
        return 2
    if not merged_root.is_dir():
        print(f"! {merged_root} not found", file=sys.stderr)
        return 2

    src: dict[str, list[str]] = collections.defaultdict(list)
    n_src_files = 0
    for t in sorted(x for x in trees.iterdir() if x.is_dir()):
        # A collected tree may sit directly as <tree>/entries or as <tree>/journal/entries depending
        # on how it was packed. Probe both rather than assuming one -- the first run of this test
        # found zero source files and reported "0 missing, 4887 invented", which is a refusal wearing
        # the shape of a pass: with nothing to compare against, every merged body looks invented.
        ent = t / "entries"
        if not ent.is_dir():
            ent = t / "journal" / "entries"
        if not ent.is_dir():
            print(f"  {t.name:16} no entries/ (looked in both <tree>/entries and <tree>/journal/entries)")
            continue
        got = collect(ent, args.normalise_ids, args.include_archive)
        nfiles = sum(len(v) for v in got.values())
        n_src_files += nfiles
        for sig, ids in got.items():
            src[sig] += [f"{t.name}:{i}" for i in ids]
        print(f"  {t.name:16} {nfiles:6} files  {len(got):6} distinct bodies")
    if not n_src_files:
        print("! no source entries were read at all -- REFUSING to report a verdict", file=sys.stderr)
        return 4

    merged = collect(merged_root / "entries", args.normalise_ids, args.include_archive)
    n_merged = sum(len(v) for v in merged.values())
    print(f"\nsource files total        : {n_src_files}")
    print(f"distinct bodies, sources  : {len(src)}")
    print(f"merged files              : {n_merged}")
    print(f"distinct bodies, merged   : {len(merged)}")

    missing = sorted(set(src) - set(merged))
    extra = sorted(set(merged) - set(src))
    print(f"\n**BODIES MISSING from merged : {len(missing)}**")
    print(f"**BODIES INVENTED in merged  : {len(extra)}**")

    for h in missing[:args.show]:
        print(f"   missing  {h[:16]}  was {sorted(src[h])[:3]}")
    for h in extra[:args.show]:
        print(f"   invented {h[:16]}  now {sorted(merged[h])[:3]}")

    ids_with_many = sum(1 for ids in merged.values() if len(ids) > 1)
    print(f"\nbodies filed under >1 id  : {ids_with_many}  "
          f"(expected 0 -- a renumber gives the body a new id and leaves none behind)")
    print(f"\nVERDICT: {'NO BODY LOST' if not missing else str(len(missing)) + ' BODY/BODIES LOST'}")
    return 0 if not missing else 1


if __name__ == "__main__":
    raise SystemExit(main())



