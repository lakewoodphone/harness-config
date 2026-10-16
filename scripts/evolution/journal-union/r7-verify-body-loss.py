#!/usr/bin/env python3
"""r7-verify-body-loss.py — did the journal union lose an entry?

THIS TOOL GAVE A FALSE VERDICT ON 2026-10-16, AND FIXING IT IS THE POINT OF THIS FILE. Its signature
(`body_sig`) is heading + body with every id token normalised, and it keeps PUNCTUATION. `journal.py`'s
own identity (`identity_of`) is the BODY alone. So when `dedupe` collapsed two copies that differed
only in a heading's dash, this tool reported bodies LOST that were live the whole time:

    pain P2561bc : body == live P2561b body (3,188 chars, equal)   -> dedupe was RIGHT
    headings     : "## P2561bc — The journal's id bands ..."  vs  "## P2561b - The journal's id bands ..."
    old verdict  : 97a6007f... vs 43b43d51...  -> reported 14 BODIES LOST

Fourteen bodies were "restored" on the strength of that reading, and `dedupe` then proposed exactly
those fourteen back. A no-loss test whose false positive causes a WRITE is worse than no test.

SO THE VERDICT IS NOW THE JOURNAL'S OWN NOTION OF IDENTITY, imported from the MERGED tree's
`tools/journal.py`, so this tool and the journal cannot disagree about what an entry is. The strict
signature is still printed, clearly labelled as informational: a heading that changed a dash lands
there, and a retired copy whose id moved lands there, and neither is a loss.

WHY THE EARLIER VERSIONS WERE ALSO WRONG, kept because the shape of the mistake repeats:
  * whole-file sha256 reported 403 lost / 377 invented on a merge that lost nothing — the header line
    carries the id, so a renumber changes the bytes;
  * stripping the header and metadata still left the id inside the heading;
  * normalising every id token left 11 phantom losses, because the merge renames into `<ID>b.md` and
    renumbered entries cite OTHER ids.

Usage:
    python3 r7-verify-body-loss.py --trees <dir of source trees> --merged <journal root>
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import importlib.util
import pathlib
import re
import sys

HEADER = "<!-- e:"
META = "<!-- j2"


def body_sig(p: pathlib.Path, normalise_ids: bool = False) -> str:
    """The strict signature: file minus header and metadata, ids normalised, whitespace collapsed."""
    lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    while lines and lines[0].startswith(HEADER):
        lines.pop(0)
    while lines and lines[-1].strip().startswith(META):
        lines.pop()
    text = "\n".join(ln.rstrip() for ln in lines).strip()
    if normalise_ids and p.stem:
        text = re.sub(r"\b[DHILPW][0-9]{1,6}[a-z]{0,3}\b", "<ID>", text)
        text = re.sub(r"\b" + re.escape(p.stem) + r"\b", "<ID>", text)
        text = " ".join(text.split())
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_tool(root: pathlib.Path):
    """Load journal.py from a tree, so identity is the journal's own definition and not a guess."""
    spec = importlib.util.spec_from_file_location("_jm_ident", root / "tools" / "journal.py")
    m = importlib.util.module_from_spec(spec)
    m.JOURNAL = root
    spec.loader.exec_module(m)
    return m


def entries_dir_of(t: pathlib.Path):
    ent = t / "entries"
    if not ent.is_dir():
        ent = t / "journal" / "entries"
    return ent if ent.is_dir() else None


def identities(ent: pathlib.Path, jm) -> set:
    out = set()
    for f in ent.rglob("*.md"):
        if "/archive/" in str(f).replace("\\", "/"):
            continue
        e = jm.parse_entry(f, f.parent.name)
        if e:
            out.add(jm.identity_of(e["kind"], e.get("heading"), e.get("body") or ""))
    return out


def strict_sigs(ent: pathlib.Path, normalise_ids: bool) -> set:
    out = set()
    for f in sorted(ent.rglob("*.md")):
        if "/archive/" in str(f).replace("\\", "/"):
            continue
        out.add(body_sig(f, normalise_ids))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trees", required=True, help="directory holding one subdir per source tree")
    ap.add_argument("--merged", required=True)
    ap.add_argument("--show", type=int, default=12)
    ap.add_argument("--normalise-ids", action="store_true")
    args = ap.parse_args()

    trees = pathlib.Path(args.trees)
    merged_root = pathlib.Path(args.merged)
    if not trees.is_dir():
        print(f"! {trees} not found", file=sys.stderr)
        return 2
    if not (merged_root / "entries").is_dir():
        print(f"! {merged_root}/entries not found", file=sys.stderr)
        return 2
    try:
        jm = load_tool(merged_root)
    except Exception as exc:                                    # noqa: BLE001
        print(f"! cannot load {merged_root}/tools/journal.py: {exc}", file=sys.stderr)
        return 2

    merged_ent = merged_root / "entries"
    merged_ids = identities(merged_ent, jm)
    merged_sigs = strict_sigs(merged_ent, args.normalise_ids)
    print(f"merged root                : {merged_root}")
    print(f"merged distinct identities : {len(merged_ids)}")

    n_src = 0
    missing: list[tuple[str, str, str]] = []
    src_sigs: set = set()
    for t in sorted(x for x in trees.iterdir() if x.is_dir()):
        ent = entries_dir_of(t)
        if not ent:
            print(f"  {t.name:16} no entries/ (looked in <tree>/entries and <tree>/journal/entries)")
            continue
        n, miss = 0, 0
        for f in sorted(ent.rglob("*.md")):
            if "/archive/" in str(f).replace("\\", "/"):
                continue
            e = jm.parse_entry(f, f.parent.name)
            if not e:
                continue
            n += 1
            if jm.identity_of(e["kind"], e.get("heading"), e.get("body") or "") not in merged_ids:
                miss += 1
                if len(missing) < 60:
                    missing.append((t.name, e["id_full"], (e.get("heading") or "")[:60]))
        src_sigs |= strict_sigs(ent, args.normalise_ids)
        n_src += n
        print(f"  {t.name:16} {n:6} entries   {miss:4} missing by identity")
    if not n_src:
        print("! no source entries were read at all -- REFUSING to report a verdict", file=sys.stderr)
        return 4

    strict_only = len(src_sigs - merged_sigs)
    print()
    print(f"source entries total          : {n_src}")
    print()
    print("**MISSING by the journal's own identity : %d**   <- DECIDES THE EXIT CODE" % len(missing))
    for t, i, h in missing[:args.show]:
        print(f"   {t:16} {i:10} {h}")
    print()
    print("strict-signature differences  : %d   (INFORMATIONAL -- a heading's punctuation or a"
          % strict_only)
    print("                                      renumbered id lands here; NOT a lost entry)")
    print()
    ok = not missing
    print("VERDICT: %s" % ("NO ENTRY LOST" if ok else "%d ENTRY/ENTRIES LOST" % len(missing)))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
