#!/usr/bin/env python3
"""r7-restore-archived.py — put retired-but-was-live entries back into the live view.

THE DEFECT THIS FIXES (pain P4251). `journal.py dedupe` (and, in this journal.py version,
`repair-ids`) retires a colliding body to `archive/...` instead of leaving it live under a
renumbered id. In a union that means bodies which were LIVE in at least one source tree leave the
live view -- `list`, `search` and `status` stop returning them -- even though their bytes are still
on disk. "The union keeps every body" and "the union keeps every body LIVE" are different sentences
and only the first is true without this step.

TWO MODES.

  --root R                                  the round-6 seven, named in TARGETS below
  --root R --from-sources TREESDIR          the GENERAL rule: every body under archive/ that is
                                            present in some source tree in TREESDIR and is not live

The general mode is the one to use after a union whose source set has changed. Measured 2026-10-16:
with nine sources, the hardcoded seven were not the whole set -- seven more bodies from
`_scratch/hc-master-deliver` were sitting in `archive/duplicates/handoff/H369..H374.md` and
`archive/collided-ids-2026-10-16/handoff/H3576.md`, and the cross-tree gate reported exactly those
seven as lost. A list of ids cannot survive a change of source set; a criterion can.

WHY NOT "RESTORE EVERYTHING UNDER archive/". Because some of it was never live: `flat-2026-09-14`
and `unabsorbed-2026-09-18` are legacy-import artefacts, not retired entries. The criterion is
"this body was live in a source tree", which is what the gate asks about, and the two agree by
construction because both use the same `body_sig`.

WHAT IT DOES: writes the archived body as a NEW live entry under a fresh id taken above the highest
id in use for that kind -- header id rewritten, and the entry's own id rewritten in its first body
line where the format puts it there. Nothing is deleted: the archive copy is left exactly where it
is, because that is the tool's own retirement area and this script has no business emptying it.

ASSERTIONS BEFORE ANY WRITE: the source exists; the target id is not already taken in `entries/` or
in `archive/`; the body is unchanged except for the id token. It prints the mapping and byte counts.

USAGE
    python3 r7-restore-archived.py --root /root/work/r8/merged-journal --from-sources /root/work/r8/trees
    python3 r7-restore-archived.py --root /root/work/r8/merged-journal --from-sources /root/work/r8/trees --apply
    python3 r7-restore-archived.py --root <tree>                 # the round-6 seven only
"""
from __future__ import annotations

import argparse
import hashlib
import pathlib
import re
import sys

# (kind, archived id) -- the seven from the round-6 union verification. Superseded by
# --from-sources, and kept because a named list is still the right instrument for a known set.
TARGETS = [
    ("handoff", "H2729"),
    ("handoff", "H3401"),
    ("handoff", "H2781"),
    ("handoff", "H458"),
    ("handoff", "H514"),
    ("pain", "P2561bc"),
    ("lessons", "L3767"),
]

ID_TOKEN = re.compile(r"\b[DHILPW][0-9]{1,6}[a-z]{0,3}\b")
KINDS = ("decisions", "handoff", "lessons", "pain", "wins")


def body_sig(path: pathlib.Path) -> str:
    """The same identity the body-loss verifier uses, so 'already live' means the same thing."""
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    while lines and lines[0].startswith("<!-- e:"):
        lines.pop(0)
    while lines and lines[-1].strip().startswith("<!-- j2"):
        lines.pop()
    text = ID_TOKEN.sub("<ID>", "\n".join(lines))
    return hashlib.sha256(" ".join(text.split()).encode()).hexdigest()


def live_signatures(ent: pathlib.Path) -> set[str]:
    out = set()
    for f in ent.rglob("*.md"):
        if "/archive/" in str(f).replace("\\", "/"):
            continue
        out.add(body_sig(f))
    return out


def source_signatures(trees: pathlib.Path) -> tuple[set[str], int]:
    """Every body live in any source tree under `trees` (each subdir holds journal/entries)."""
    out: set[str] = set()
    n = 0
    for t in sorted(x for x in trees.iterdir() if x.is_dir()):
        ent = t / "entries"
        if not ent.is_dir():
            ent = t / "journal" / "entries"
        if not ent.is_dir():
            continue
        for f in ent.rglob("*.md"):
            if "/archive/" in str(f).replace("\\", "/"):
                continue
            out.add(body_sig(f))
            n += 1
    return out, n


def highest_id(entries: pathlib.Path, archive: pathlib.Path, kind: str) -> int:
    """The highest numeric id in use for a kind, across live entries AND the archive."""
    top = 0
    for base in (entries, archive):
        d = base / kind
        if not d.is_dir():
            continue
        for f in d.glob("*.md"):
            m = re.match(r"^[DHILPW]([0-9]+)", f.stem)
            if m:
                top = max(top, int(m.group(1)))
    return top


def archived_candidates(root: pathlib.Path) -> list[tuple[str, str, pathlib.Path]]:
    """(kind, stem, path) for every entry file under archive/, whatever subdirectory it is in."""
    out = []
    arch = root / "archive"
    if not arch.is_dir():
        return out
    for p in sorted(arch.rglob("*.md")):
        if p.parent.name in KINDS:
            out.append((p.parent.name, p.stem, p))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--from-sources", default=None,
                    help="a directory of source trees; restore EVERY archived body that is live "
                         "in one of them and is not live in the merged tree")
    args = ap.parse_args()
    root = pathlib.Path(args.root)
    ent = root / "entries"
    arc = root / "archive"
    if not ent.is_dir():
        print(f"! {ent} not found -- not a journal tree", file=sys.stderr)
        return 2

    already_live = live_signatures(ent)
    print(f"root: {root}")
    print(f"live bodies: {len(already_live)}")

    # ── choose the targets ───────────────────────────────────────────────────────────────────────
    if args.from_sources:
        trees = pathlib.Path(args.from_sources)
        if not trees.is_dir():
            print(f"! {trees} not found -- cannot judge which archived bodies were live", file=sys.stderr)
            return 2
        src, n_src = source_signatures(trees)
        print(f"source bodies: {len(src)}  (from {n_src} files across {trees})")
        if not src:
            print("! no source bodies were read at all -- REFUSING to guess", file=sys.stderr)
            return 4
        targets: list[tuple[str, str, pathlib.Path]] = []
        already_live_archived = 0
        foreign = 0
        for kind, stem, p in archived_candidates(root):
            s = body_sig(p)
            if s in already_live:
                already_live_archived += 1
                continue
            if s not in src:
                foreign += 1          # never live in a source: legacy-import artefact, leave it
                continue
            targets.append((kind, stem, p))
        print(f"archived under archive/: {len(archived_candidates(root))} file(s)")
        print(f"  of those, body already live elsewhere : {already_live_archived}")
        print(f"  body in no source tree (left alone)   : {foreign}")
        print(f"  TO RESTORE (was live, is not live now): {len(targets)}")
    else:
        targets = []
        for kind, old in TARGETS:
            p = arc / "duplicates" / kind / f"{old}.md"
            if p.is_file():
                targets.append((kind, old, p))
            else:
                # the archive layout moved in later journal.py versions; find it wherever it is
                hits = [q for k, st, q in archived_candidates(root) if k == kind and st == old]
                if hits:
                    targets.append((kind, old, hits[0]))
                else:
                    print(f"! {old}: no archived copy found under {arc}", file=sys.stderr)
                    return 1

    next_id: dict[str, int] = {}
    for kind, _st, _p in targets:
        if kind not in next_id:
            next_id[kind] = highest_id(ent, arc, kind) + 1

    plan: list[tuple[str, str, str, pathlib.Path]] = []
    problems: list[str] = []
    skipped: list[str] = []
    for kind, old, src in targets:
        sig = body_sig(src)
        if sig in already_live:
            skipped.append(old)            # IDEMPOTENCE BY CONTENT, not by id: see below
            continue
        new = f"{old[0]}{next_id[kind]}"
        next_id[kind] += 1
        dst = ent / kind / f"{new}.md"
        if dst.exists():
            problems.append(f"{old}: target {dst} already exists")
            continue
        plan.append((kind, old, new, src))
        # A SECOND ARCHIVED COPY OF THE SAME BODY MUST NOT ALSO BE RESTORED. Without this the plan
        # is built against the pre-write state, so two archive files carrying one body (the same
        # entry retired twice, under two ids) become two live copies of it.
        already_live.add(sig)

    if skipped:
        print(f"already live, skipped (idempotent): {', '.join(skipped)}")

    if problems:
        print("! refusing to write:", file=sys.stderr)
        for p in problems:
            print("   " + p, file=sys.stderr)
        return 1

    print(f"{'kind':9} {'old':9} -> {'new':9}  bytes   body-sha(before) -> (after)")
    for kind, old, new, src in plan:
        raw = src.read_bytes()
        text = raw.decode("utf-8")
        lines = text.splitlines(keepends=True)
        # 1. the header line carries the id between pipes
        if "|" in lines[0]:
            lines[0] = lines[0].replace(f"|{old}|", f"|{new}|")
        # 2. some kinds put their own id at the start of the first body line; rewrite only that one
        for i in range(1, len(lines)):
            if not lines[i].strip():
                continue
            if re.search(r"(?<![A-Za-z0-9])" + re.escape(old) + r"(?![A-Za-z0-9])", lines[i]):
                lines[i] = re.sub(r"(?<![A-Za-z0-9])" + re.escape(old) + r"(?![A-Za-z0-9])", new, lines[i])
            break
        out = "".join(lines)
        before = hashlib.sha256(ID_TOKEN.sub("<ID>", " ".join(text.split())).encode()).hexdigest()
        after = hashlib.sha256(ID_TOKEN.sub("<ID>", " ".join(out.split())).encode()).hexdigest()
        flag = "same" if before == after else "CHANGED-BEYOND-ID"
        print(f"{kind:9} {old:9} -> {new:9}  {len(raw):5}   {before[:12]} -> {after[:12]}  {flag}")
        if before != after:
            problems.append(f"{old}: body changes by more than the id token")
        if args.apply:
            (ent / kind).mkdir(parents=True, exist_ok=True)
            (ent / kind / f"{new}.md").write_bytes(out.encode("utf-8"))

    if problems:
        print("\n! refusing: " + "; ".join(problems), file=sys.stderr)
        return 1

    if args.apply:
        print(f"\nwrote {len(plan)} live entr(ies). The archive copies are UNTOUCHED.")
        print("next: the entry body may now differ from its recorded sha= -- run "
              "`journal.py check --fix`, which re-emits through the writer and recomputes it")
    else:
        print(f"\nmeasure only -- would write {len(plan)} live entr(ies). Re-run with --apply.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
