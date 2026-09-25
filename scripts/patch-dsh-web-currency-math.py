#!/usr/bin/env python3
"""Turn OFF single-dollar inline math in the DSH Web frontend, so currency is text and not LaTeX.

THE BUG (measured 2026-09-25, ZABZ-YOGA). A message containing two dollar amounts renders as
mathematics between them. In the DSH Web GUI, the tail of a message that read

    One honest gap: the $100 is a **shop expense**, not a customer receipt, so it doesn't change
    his `payment_state` ($320 in, $1,600 on success).

came out as

    One honest gap: the $100isa**shopexpense**,notacustomerreceipt,soitdoesn'tchangehis
    `payment_state`($320 in, $1,600 on success).

Every word between the first `$` and the next `$` was typeset as LaTeX: spaces dropped, the hyphen
rendered as U+2212 MINUS, the `**` markers printed literally. A second message had the same fate in
its own quotes: `$320 deposit paid 2026-09-17 + $100 open-cover fee` rendered as
`320depositpaid2026−09−17+100`. The shop's text is full of money, so this is not an edge case.

THE CAUSE. The frontend bundle contains `micromark-extension-math`, whose `singleDollarTextMath`
option defaults to TRUE. In the minified bundle that default is the branch

    function t4(e){let n={}.singleDollarTextMath;return n==null&&(n=!0),{tokenize:r,resolve:n4,...}
                                                      ^^^^^^  <- default true

and the tokenizer bails out of math mode on a single `$` only when that flag is false:

    function h(k){return k===36?(a.consume(k),o++,h):o<2&&!n?s(k):(a.exit(...),f(k))}

FIX. Flip that default from `!0` to `!1`. `$$...$$` display math keeps working (it takes the
double-dollar path, `o<2` is false there); single `$` becomes ordinary text, which is what a shop's
prose needs. The edit is a same-length literal flip, so it cannot introduce a syntax error.

WHERE. `node_modules/@deepseek-ai/dsh-web-frontend/dist/assets/vendor-*.js` inside the DSH install
(this machine: the npx cache). That file is a published build artifact, so a patch there is lost
whenever the package is reinstalled -- which is why this script exists and is idempotent. Run it after
any DSH upgrade; `--check` reports without writing and exits 1 if the fix is missing.

Usage:
  patch-dsh-web-currency-math.py            # apply (idempotent), report what changed
  patch-dsh-web-currency-math.py --check    # verify only; exit 1 if the bundle still enables it
  patch-dsh-web-currency-math.py --root DIR # a different DSH install root (node_modules parent)
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import pathlib
import sys

#: Only *explicit* install locations are searched. A recursive glob over a home directory walked
#: 100k+ source files the first time this ran (measured 2026-09-25: the apply did not finish in five
#: minutes and never reached the write) -- a patch tool must not be slower than the bug it fixes.
DEFAULT_ROOTS = [
    # the npx cache install `dsh web` runs from on ZABZ-YOGA
    pathlib.Path.home() / "AppData/Local/npm-cache/_npx",
    # global npm installs, for other machines
    pathlib.Path.home() / "AppData/Roaming/npm/node_modules",
    pathlib.Path("/usr/lib/node_modules"),
    pathlib.Path("/usr/local/lib/node_modules"),
    pathlib.Path.home() / ".npm-global/lib/node_modules",
]

OLD = b"{}.singleDollarTextMath;return n==null&&(n=!0)"
NEW = b"{}.singleDollarTextMath;return n==null&&(n=!1)"
MARKER = b"singleDollarTextMath"


def candidate_bundles(root: pathlib.Path) -> list[pathlib.Path]:
    pats = [
        str(root / "**/dsh-web-frontend/dist/assets/vendor-*.js"),
        str(root / "**/node_modules/@deepseek-ai/dsh-web-frontend/dist/assets/vendor-*.js"),
    ]
    out: list[pathlib.Path] = []
    for p in pats:
        out.extend(pathlib.Path(x) for x in glob.glob(p, recursive=True))
    return sorted(set(out))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--root", default=None)
    args = ap.parse_args()

    roots = [pathlib.Path(args.root)] if args.root else DEFAULT_ROOTS
    bundles: list[pathlib.Path] = []
    for r in roots:
        if r.exists():
            bundles.extend(candidate_bundles(r))
    if not bundles:
        print("no dsh-web-frontend bundle found under: %s" % ", ".join(str(r) for r in roots))
        return 2

    rc = 0
    for b in bundles:
        # BYTES, never text. A text-mode read/write on Windows rewrote every LF as CRLF the first
        # time this ran (measured 2026-09-25: the bundle grew 411 bytes for a one-character fix),
        # which is a much larger change than the bug it was fixing. A byte replace cannot do that,
        # and it makes the invariant checkable: the file size must be EXACTLY unchanged.
        raw = b.read_bytes()
        has_old = OLD in raw
        has_new = NEW in raw
        digest = hashlib.sha256(raw).hexdigest()[:16]
        state = ("patched" if has_new and not has_old else
                 "UNPATCHED" if has_old else "no-math-extension")
        print("%-9s %s  (%d bytes, sha256:%s)" % (state, b, len(raw), digest))
        if MARKER not in raw:
            continue
        if args.check:
            if has_old:
                rc = 1
            continue
        if has_new and not has_old:
            print("   already patched - nothing to do")
            continue
        if raw.count(OLD) != 1:
            print("   REFUSING: expected exactly one occurrence of %r, found %d"
                  % (OLD, raw.count(OLD)))
            rc = 3
            continue
        backup = b.with_suffix(b.suffix + ".orig-currency-math")
        if not backup.exists():
            backup.write_bytes(raw)
            print("   backup: %s" % backup)
        b.write_bytes(raw.replace(OLD, NEW, 1))
        after = b.read_bytes()
        print("   patched -> singleDollarTextMath default is now false (bytes %d -> %d, unchanged=%s)"
              % (len(raw), len(after), len(raw) == len(after)))
        print("   verify: old present=%s new present=%s" % (OLD in after, NEW in after))
    return rc


if __name__ == "__main__":
    sys.exit(main())
