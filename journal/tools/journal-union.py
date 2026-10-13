#!/usr/bin/env python3
"""journal-union.py — make two journal trees hold the same entries, in BOTH directions.

THE GAP THIS CLOSES, measured 2026-10-13. The entries were unioned by hand twice (149 one way, 341
the other) and verified identical -- 3,819 entries and 401 open pain on both trees. Hours later they
were **13 entries apart again**, because both trees write and nothing moves entries between them. So
"I consolidated the journal" was true and "the journal is one record" was not.

A record that exists in several copies gets quoted as if there were one. That is not a hypothetical:
three sessions in one day quoted three different open-pain counts and ALL THREE WERE RIGHT, because
they were reading different trees.

WHY A UNION AND NOT A MERGE-BY-DATE. `entries/<kind>/<id>.md` is content-addressed by id, and
`status.tsv` is append-only. So the correct operation is a set union of files and of rows -- never a
timestamp comparison, which would silently prefer one side's version of an id both sides have.

WHAT IT REFUSES TO DO, because the one real hazard is an id that means two things:
  * an id present on BOTH sides with DIFFERENT bytes is reported and LEFT ALONE -- that is the
    collision `journal.py repair-ids` exists for, and guessing which copy wins is how one id comes to
    mean two entries. It exits 3 and names them.
  * nothing is deleted, ever. Union only adds.
  * `status.tsv` rows are unioned as whole lines: append-only means a row that exists is never
    rewritten, so the union of rows is the only correct operation.

USAGE
    journal-union.py --remote secratary-cloud                    # dry run: report the difference
    journal-union.py --remote secratary-cloud --apply            # union both ways
    journal-union.py --remote secratary-cloud --apply --pull-only

EXIT  0 nothing to do · 1 a union was available (dry run) or done (--apply) · 2 could not run · 3 an
      id exists on both sides with different content -- FIX THAT FIRST, do not union.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path

DD = {"ssh": ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=12"]}


def run(cmd: list[str], text: bool = True, **kw) -> subprocess.CompletedProcess:
    """Subprocess with BOTH modes available. The tar transfers need bytes; everything else is text.

    (First draft hardcoded `text=True` and then called it with `text=False`, which is a TypeError --
    found by reading the file before running it, which is the cheaper of the two ways.)"""
    return subprocess.run(cmd, capture_output=True, text=text, encoding=None if not text else "utf-8",
                          errors=None if not text else "replace", **kw)


def sha(b: bytes) -> str:
    """sha of the content with line endings NORMALISED.

    THE BUG THIS FIXES, and it produced 122 false collisions the first time it ran. This checkout's
    working tree carries CRLF (Windows) and the authority's carries LF, so a byte comparison said
    "122 ids exist on both sides with different content" -- when nearly all of them were the same
    entry with different line endings.

    That is the THIRD time in one session that a byte comparison across these two machines produced a
    false verdict: `preset-drift.py` (twice, against `sync.py`, which normalises deliberately) and
    now here. The question this check actually asks is "does this id MEAN two different things" --
    never "are these bytes identical" -- so normalise before asking it.
    """
    return hashlib.sha256(b.replace(b"\r\n", b"\n")).hexdigest()


def remote_list(remote: str, root: str) -> list[str]:
    """Relative paths of every entry file on the remote, plus status.tsv as a marker."""
    out = run(DD["ssh"] + [remote, f"cd {root}/journal/entries && find . -name '*.md' -printf '%P\\n'"])
    if out.returncode != 0:
        print(f"journal-union: cannot list {root}/journal/entries on {remote}: "
              f"{(out.stderr or '')[:200]}", file=sys.stderr)
        sys.exit(2)
    return [l for l in (out.stdout or "").splitlines() if l.strip()]


def remote_fetch(remote: str, root: str, rels: list[str], dest: Path) -> None:
    """Fetch the named entry files, byte-exact, via a tar built on the remote.

    The want-list is NORMALISED on the remote (`tr -d '\\r'`). Passing a newline-joined list to `ssh`
    through this shell arrives with CRLF, so `tar -T` looked for `decisions/D1.md\\r` and failed on
    every line -- the same trap as the round-1 manifest, where every path had a trailing `\\r` and the
    command produced `[exit code: 1]` with no useful message. Strip it at the far end, where the bytes
    actually land.
    """
    run(DD["ssh"] + [remote, "cat > /tmp/ju-want.txt"], input="\n".join(rels) + "\n")
    out = run(DD["ssh"] + [remote,
                           f"cd {root}/journal/entries && tr -d '\\r' < /tmp/ju-want.txt > /tmp/ju-want2.txt "
                           "&& tar -czf /tmp/ju.tar.gz -T /tmp/ju-want2.txt && cat /tmp/ju.tar.gz"],
              text=False)
    if out.returncode != 0:
        print(f"journal-union: remote tar failed: {(out.stderr or b'')[:300]!r}", file=sys.stderr)
        sys.exit(2)
    tarpath = dest / "ju.tar.gz"
    tarpath.write_bytes(out.stdout)
    with tarfile.open(tarpath, "r:gz") as tf:
        for m in tf.getmembers():
            if not m.isfile():
                continue
            if "/" not in m.name or m.name.startswith("..") or m.name.startswith("/"):
                print(f"journal-union: REFUSING a tar member outside the kinds tree: {m.name}",
                      file=sys.stderr)
                sys.exit(2)
            target = dest / "entries" / m.name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(tf.extractfile(m).read())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--remote", required=True)
    ap.add_argument("--remote-root", default="/root/code/harness-config")
    ap.add_argument("--local-root", default=None)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--pull-only", action="store_true")
    ap.add_argument("--push-only", action="store_true")
    a = ap.parse_args()

    local = Path(a.local_root).expanduser() if a.local_root else \
        Path(__file__).resolve().parents[2]
    if not (local / "journal" / "entries").is_dir():
        print(f"journal-union: no journal/entries under {local}", file=sys.stderr)
        return 2

    rels = remote_list(a.remote, a.remote_root)
    theirs = {r: None for r in rels}
    mine = {str(p.relative_to(local / "journal" / "entries")).replace(os.sep, "/"): p
            for p in (local / "journal" / "entries").rglob("*.md")}

    only_theirs = sorted(set(theirs) - set(mine))
    only_mine = sorted(set(mine) - set(theirs))
    both = sorted(set(theirs) & set(mine))

    print(f"{a.remote}:{a.remote_root}/journal/entries   {len(rels)} entries")
    print(f"{local}/journal/entries                     {len(mine)} entries")
    print(f"  only there : {len(only_theirs)}")
    print(f"  only here  : {len(only_mine)}")
    print(f"  both       : {len(both)}   (checked for one id meaning two things)")

    # The one hazard: the same id with different bytes. Report, never guess.
    tmp = Path(tempfile.mkdtemp(prefix="ju-"))
    collisions = []
    if both:
        remote_fetch(a.remote, a.remote_root, both, tmp)
        for r in both:
            rp = tmp / "entries" / r
            if rp.is_file() and sha(rp.read_bytes()) != sha((mine[r]).read_bytes()):
                collisions.append(r)
    if collisions:
        print(f"\nREFUSING: {len(collisions)} id(s) exist on BOTH sides with DIFFERENT content. "
              "That is the collision `journal.py repair-ids` exists for, and choosing a winner by "
              "hand is how one id comes to mean two entries. Nothing was written.", file=sys.stderr)
        for c in collisions[:20]:
            print(f"  {c}", file=sys.stderr)
        return 3

    union_total = len(mine) + len(only_theirs)
    if not only_theirs and not only_mine:
        print("\nidentical -- nothing to do. The two trees agree.")
        return 0

    if not a.apply:
        print(f"\nDRY RUN: a union would bring both trees to {union_total} entries "
              f"({len(only_theirs)} pulled, {len(only_mine)} pushed). Nothing was written.")
        for r in only_theirs[:5]:
            print(f"  PULL {r}")
        for r in only_mine[:5]:
            print(f"  PUSH {r}")
        return 1

    # ---- pull ----
    pulled = 0
    if only_theirs and not a.push_only:
        remote_fetch(a.remote, a.remote_root, only_theirs, tmp)
        for r in only_theirs:
            src = tmp / "entries" / r
            dst = local / "journal" / "entries" / r
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
            pulled += 1
        print(f"\npulled {pulled} entry/entries into {local}")

    # ---- push ----
    pushed = 0
    if only_mine and not a.pull_only:
        bundle = tmp / "push.tar.gz"
        with tarfile.open(bundle, "w:gz") as tf:
            for r in only_mine:
                tf.add(mine[r], arcname=r)
        out = run(DD["ssh"] + [a.remote,
                               f"cd {a.remote_root}/journal/entries && "
                               "n=0; while IFS= read -r f; do [ -f \"$f\" ] && echo \"OVERWRITE $f\"; done"],
                  input="\n".join(only_mine) + "\n")
        if "OVERWRITE" in (out.stdout or ""):
            print("journal-union: REFUSING -- a push would overwrite an existing remote entry:\n"
                  + (out.stdout or "")[:400], file=sys.stderr)
            return 3
        run(DD["ssh"] + [a.remote, "cat > /tmp/ju-push.tar.gz"], text=False,
            input=bundle.read_bytes())
        out = run(DD["ssh"] + [a.remote,
                               f"cd {a.remote_root}/journal/entries && tar -xzf /tmp/ju-push.tar.gz "
                               "&& find . -name '*.md' | wc -l"])
        if out.returncode != 0:
            print(f"journal-union: remote extract failed: {(out.stderr or '')[:200]}", file=sys.stderr)
            return 2
        pushed = len(only_mine)
        print(f"pushed {pushed} entry/entries to {a.remote} (now {out.stdout.strip()} there)")

    # ---- status.tsv: append-only, so the union of rows is the only correct operation ----
    st = run(DD["ssh"] + [a.remote, f"cat {a.remote_root}/journal/state/status.tsv"], text=False)
    theirs_rows = (st.stdout or b"").decode("utf-8", "replace").splitlines()
    mine_rows = (local / "journal" / "state" / "status.tsv").read_text(encoding="utf-8").splitlines()
    add_mine = [r for r in mine_rows if r and r not in theirs_rows]
    add_theirs = [r for r in theirs_rows if r and r not in mine_rows]
    if not a.push_only and add_theirs:
        with open(local / "journal" / "state" / "status.tsv", "a", encoding="utf-8") as f:
            f.write("\n".join(add_theirs) + "\n")
        print(f"status.tsv: +{len(add_theirs)} row(s) here")
    if not a.pull_only and add_mine:
        run(DD["ssh"] + [a.remote, "cat >> "
                         f"{a.remote_root}/journal/state/status.tsv"],
            input="\n".join(add_mine) + "\n")
        print(f"status.tsv: +{len(add_mine)} row(s) there")
    if not add_mine and not add_theirs:
        print("status.tsv: identical")

    print(f"\nunion complete. Both trees should now hold {union_total} entries; verify with "
          "`journal.py check` on each, which is the only thing that proves it.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
