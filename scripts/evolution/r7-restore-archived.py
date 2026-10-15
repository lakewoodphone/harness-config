#!/usr/bin/env python3
"""r7-restore-archived.py — put the seven retired-but-was-live entries back into the live view.

THE DEFECT THIS FIXES (pain P4251). `journal.py dedupe` retires a colliding body to
`archive/duplicates/<id>.md` instead of renumbering it to a fresh LIVE id. In a five-tree union that
means seven bodies which were LIVE in at least one source tree would leave the live view -- `list`,
`search` and `status` would stop returning them -- even though their bytes are still on disk.

Measured 2026-10-15 against the candidate union at /root/work/r7/merged-journal:

    id         live in                 -> the candidate keeps, live under that id
    H2729      mac  (344 chars)           yoga's "Queue walk: Golembick..." (7,087 chars)
    H3401      mac                        a different body
    H2781      cloud+linux+tech           a different body
    H458       cloud+linux+tech           a different body
    H514       cloud+linux+tech           a different body
    P2561bc    cloud+linux+tech           a different body
    L3767      cloud+yoga                 a different body

WHAT THIS DOES: for each of those seven, writes the archived body as a NEW live entry under a fresh id
taken above the highest id in use for that kind -- header id rewritten, and the entry's own id rewritten
in its first body line where the format puts it there. Nothing is deleted: the `archive/duplicates/`
copy is left exactly where it is, because that is the tool's own retirement area and this script has no
business emptying it.

ASSERTIONS BEFORE ANY WRITE: the source exists; the target id is not already taken in `entries/` or in
`archive/`; the body is unchanged except for the id token. It prints the mapping and the byte counts.

USAGE
    python3 r7-restore-archived.py --root /root/work/r7/merged-journal              # measure
    python3 r7-restore-archived.py --root /root/work/r7/merged-journal --apply
"""
from __future__ import annotations

import argparse
import hashlib
import pathlib
import re
import sys

# (kind, archived id) -- the seven from the union verification
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    root = pathlib.Path(args.root)
    ent = root / "entries"
    arc = root / "archive" / "duplicates"
    if not ent.is_dir():
        print(f"! {ent} not found -- not a journal tree", file=sys.stderr)
        return 2

    next_id: dict[str, int] = {}
    for kind, _ in TARGETS:
        if kind not in next_id:
            next_id[kind] = highest_id(ent, arc, kind) + 1

    plan: list[tuple[str, str, str, pathlib.Path]] = []
    problems: list[str] = []
    # IDEMPOTENCE BY CONTENT, not by id. The first version guarded only on "does this NEW id already
    # exist", which is no guard at all: re-running would allocate a higher id each time and create a
    # second live copy of the same body on every run. The question that matters is whether the BODY
    # is already live, so ask that.
    already_live = live_signatures(ent)
    skipped: list[str] = []
    for kind, old in TARGETS:
        src = arc / kind / f"{old}.md"
        if not src.is_file():
            problems.append(f"{old}: no archived copy at {src}")
            continue
        if body_sig(src) in already_live:
            skipped.append(old)
            continue
        new = f"{old[0]}{next_id[kind]}"
        next_id[kind] += 1
        dst = ent / kind / f"{new}.md"
        if dst.exists():
            problems.append(f"{old}: target {dst} already exists")
            continue
        plan.append((kind, old, new, src))

    if skipped:
        print(f"already live, skipped (idempotent): {', '.join(skipped)}")

    if problems:
        print("! refusing to write:", file=sys.stderr)
        for p in problems:
            print("   " + p, file=sys.stderr)
        return 1

    print(f"root: {root}")
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
        print(f"\nwrote {len(plan)} live entr(ies). The archive/duplicates/ copies are UNTOUCHED.")
        print("next: python3 journal/tools/journal.py --root %s index" % root)
        print("      python3 journal/tools/journal.py --root %s check" % root)
    else:
        print(f"\nmeasure only -- would write {len(plan)} live entr(ies). Re-run with --apply.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
