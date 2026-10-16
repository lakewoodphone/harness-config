#!/usr/bin/env python3
"""apply-cross-tree.py — put the `check --cross-tree` rule into a journal.py that does not have it.

WHY A SCRIPT AND NOT AN EDIT. The estate ships four different journal.py copies, so the same rule has
to land in files of different generations. A hand edit does not travel and cannot be verified on the
next machine; this does, and it refuses rather than guessing.

WHAT IT CHECKS BEFORE WRITING, and refuses on any of them:
  * the file parses as Python (`compile`), before and after;
  * `s = add("check", ...)` exists            -- the flag has somewhere to attach;
  * `def cmd_check(` exists, and inside it `errors` and `infos` are the accumulator names;
  * a `by_hash = {}` line exists AFTER `def cmd_check` -- the insertion point;
  * `cross_tree` is not already present      -- idempotent, so a second run is a no-op.

HOW IT WRITES. To a temp file in the same directory, then `os.replace` -- atomic, so a session
reading the tool mid-patch sees one version or the other, never half of each. The original is kept
beside it as `<name>.pre-cross-tree-<UTC>`.

The inserted block is deliberately generation-proof: it imports pathlib inside itself, tolerates a
`load_entries()` that returns a list rather than a tuple, and guards the entries-cache clear with
NameError so an older copy without `_ENTRIES_CACHE` still runs.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import os
import pathlib
import shutil
import sys

BLOCK_FLAG = '''    s.add_argument("--cross-tree", dest="cross_tree", default=None, metavar="DIR",
                   help="also compare against other journal trees: DIR holds one subdirectory per "
                        "tree (each with entries/ or journal/entries). Without it, check can only "
                        "test this tree against ITSELF, which is why a forked store reports 0 errors")
'''

BLOCK_GLOBAL = '''    # `global` because the --cross-tree block below re-points JOURNAL at each other tree and
    # restores it; without it Python treats JOURNAL as a LOCAL for the whole function.
    global JOURNAL
'''

BLOCK_XT = '''    # ── CROSS-TREE ───────────────────────────────────────────────────────────────────────────────
    # The duplicate-id rule above is INTRA-tree, and that is why a forked journal looks healthy:
    # no tree can collide with itself. Measured 2026-10-16: `check` reported 0 errors in every tree
    # of this estate while ids carried two and three different bodies across them -- D3034 meant
    # "the shop's money & customer tracking survives long-term" on two trees and "Weitman SD copy
    # route" on a third, so a `resolve` on either side closes the WRONG decision with no error
    # raised. OFF unless --cross-tree DIR is given, so an offline machine stays checkable.
    _xt = getattr(args, "cross_tree", None)
    if _xt:
        import pathlib as _xt_pathlib
        _xt_base = _xt_pathlib.Path(_xt)
        if not _xt_base.is_dir():
            errors.append("--cross-tree %s is not a directory" % _xt_base)
        else:
            _xt_mine = {}
            for _e in entries:
                _xt_mine.setdefault((_e["kind"], _e["id_full"]), set()).add(_e.get("hash") or "")
            _xt_cmp, _xt_unseen = 0, []
            for _t in sorted(x for x in _xt_base.iterdir() if x.is_dir()):
                _ent = _t / "entries"
                if not _ent.is_dir():
                    _ent = _t / "journal" / "entries"
                if not _ent.is_dir():
                    _xt_unseen.append(_t.name)
                    continue
                _prev = JOURNAL
                JOURNAL = _ent.parent
                try:
                    _ENTRIES_CACHE.clear()
                except NameError:
                    pass
                try:
                    _xt_res = load_entries()
                finally:
                    JOURNAL = _prev
                    try:
                        _ENTRIES_CACHE.clear()
                    except NameError:
                        pass
                _xt_other = _xt_res[0] if isinstance(_xt_res, tuple) else _xt_res
                _xt_cmp += 1
                _xt_theirs = {}
                for _e in _xt_other:
                    _xt_theirs.setdefault((_e["kind"], _e["id_full"]), set()).add(_e.get("hash") or "")
                _xt_clash = sorted(k for k, _hs in _xt_theirs.items()
                                   if _xt_mine.get(k) and (_hs - _xt_mine[k]))
                for _k in _xt_clash:
                    errors.append("cross-tree id %s in %s carries a different body in %s"
                                  % (_k[1], _k[0], _t.name))
                if _xt_clash:
                    infos.append("%s: %d id(s) differ from this tree" % (_t.name, len(_xt_clash)))
            infos.append("--cross-tree: compared %d tree(s) under %s%s"
                         % (_xt_cmp, _xt_base,
                            ("; NO ENTRIES FOUND in " + ", ".join(_xt_unseen)) if _xt_unseen else ""))
            if _xt_cmp == 0:
                errors.append("--cross-tree %s held no readable journal tree: %s"
                              % (_xt_base, ", ".join(_xt_unseen) or "nothing"))
'''


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    p = pathlib.Path(args.file)
    # newline="" on both sides: text mode would translate \n -> \r\n on a Windows run and rewrite
    # every line of a file that lives in git as LF, turning a one-block patch into a whole-file diff.
    # Builtin open(), not Path.open(): `newline` on Path.open does not exist before Python 3.10 and
    # her Mac mini runs the system 3.9.
    with open(str(p), "r", encoding="utf-8", newline="") as fh:
        src = fh.read()
    lines = src.split("\n")

    if "cross_tree" in src:
        print("ALREADY PRESENT -- nothing to do (idempotent)")
        return 0

    def one(frag, start=0):
        for i in range(start, len(lines)):
            if frag in lines[i]:
                return i
        return -1

    i_add = one('add("check"')
    i_def = one("def cmd_check")
    if i_add < 0 or i_def < 0:
        print("REFUSING: no `add(\"check\"` (%d) or `def cmd_check` (%d)" % (i_add, i_def),
              file=sys.stderr)
        return 1
    i_by = one("by_hash = {}", i_def)
    if i_by < 0:
        print("REFUSING: no `by_hash = {}` after cmd_check -- no safe insertion point",
              file=sys.stderr)
        return 1
    body = "\n".join(lines[i_def:i_by])
    for need in ("errors", "infos"):
        if need not in body:
            print("REFUSING: cmd_check does not use the accumulator `%s` in this generation"
                  % need, file=sys.stderr)
            return 1
    i_global = one("global JOURNAL", i_def)
    need_global = not (i_def < i_global < i_by)

    print("file            :", p)
    print("add('check') at :", i_add + 1)
    print("cmd_check at    :", i_def + 1)
    print("insert block at :", i_by + 1, "(by_hash = {})")
    print("needs global    :", need_global)
    if not args.apply:
        print("\nMEASURE ONLY -- re-run with --apply")
        return 0

    # FIND the point just after cmd_check's docstring, if it has one, so `global` does not displace
    # the docstring (which must stay the first statement).
    j = i_def + 1
    while j < i_by and not lines[j].strip():
        j += 1
    if j < i_by and lines[j].lstrip().startswith('"""'):
        j += 1                                     # skip past the opening line
        while j < i_by and '"""' not in lines[j]:
            j += 1
        j += 1                                     # past the closing line

    # INSERT IN DESCENDING INDEX ORDER. The three insertion points come from the ORIGINAL line
    # numbering, and inserting at a low index shifts every index above it. Doing them top-down put
    # the --cross-tree argument four lines above the `check` subparser: it compiled, `check` still
    # passed, and the flag silently attached to a DIFFERENT subparser. Only reading `check --help`
    # showed it. Highest index first, so every earlier index is still valid when it is used.
    out = list(lines)
    ins = [(i_by, BLOCK_XT.rstrip("\n")), (i_add + 1, BLOCK_FLAG.rstrip("\n"))]
    if need_global:
        ins.append((j, BLOCK_GLOBAL.rstrip("\n")))
    for idx, text in sorted(ins, key=lambda kv: -kv[0]):
        out.insert(idx, text)
    new = "\n".join(out)

    try:
        compiled = compile(new, str(p), "exec")
    except SyntaxError as exc:
        print("REFUSING: the patched file does not compile: %s" % exc, file=sys.stderr)
        return 1
    assert compiled is not None

    stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = p.with_name(p.name + ".pre-cross-tree-" + stamp)
    shutil.copy2(p, backup)
    tmp = p.with_name(p.name + ".xt-tmp")
    with open(str(tmp), "w", encoding="utf-8", newline="") as fh:
        fh.write(new)
    os.replace(str(tmp), str(p))
    print("\nAPPLIED")
    print("  backup :", backup)
    # CHARS and BYTES are not the same number in this file: it is full of em-dashes and box-drawing
    # characters, so 254,892 characters land as 255,330 bytes. Reporting one under the other's name
    # sent a session looking for a 438-byte edit that had not happened.
    print("  size   : %d -> %d chars   (%d -> %d bytes)"
          % (len(src), len(new), len(src.encode("utf-8")), len(new.encode("utf-8"))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
