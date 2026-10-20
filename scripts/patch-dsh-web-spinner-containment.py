#!/usr/bin/env python3
"""Contain the Web frontend's spinner animations so an idle window stops repainting its ancestors.

WHY THIS EXISTS. The app bundle's spinners animate forever (`._spinner*` keyframes). In a
multi-window launcher every open window keeps its own compositor layer dirty for as long as any
spinner is on screen; `contain: layout paint` on the spinner elements stops that layer from
dirtying the rest of the frame. Measured on ZABZ-YOGA 2026-10-05 (docs/dsh-at-scale/
97-client-per-window-cost.md) and re-measured 2026-10-20 against 0.2.1-rc.2: the upstream bundle
still ships the same five spinner classes with no containment, so this patch is still needed.

WHY IT IS A PATCHER AND NOT A HAND EDIT. The target is `dist/assets/index-<hash>.css` -- a
published build artifact whose NAME changes with every release (`index-BPHePDI_.css` on 0.2.0,
`index-BxpfOGf3.css` on 0.2.1-rc.2). A hand edit is therefore lost on the next install and the
install-time audit cannot tell "lost" from "not needed" (P3170). This script finds the bundle by
glob, reads the spinner class names out of the file, and appends one rule -- idempotently, and
refusing rather than guessing if the classes are gone.

Usage:
  patch-dsh-web-spinner-containment.py --root DIR           # apply (idempotent)
  patch-dsh-web-spinner-containment.py --root DIR --check   # 0 present, 1 missing, 4 anchor absent
"""
from __future__ import annotations

import argparse
import glob
import pathlib
import re
import sys

MARKER = "harness-patch:spinner-containment"
# The hashed class names look like `_spinner_u7vgf_45`, `_spinnerMotion_1i3xo_42`. Read them out of
# the bundle rather than hardcoding a release's hashes: the suffix changes with every build.
CLASS_RE = re.compile(r"\.(_spinner[A-Za-z0-9]*_[a-z0-9]+_\d+)")


def bundles(root: pathlib.Path) -> list[pathlib.Path]:
    pat = str(root / "node_modules" / "@deepseek-ai" / "dsh-web-frontend" / "dist" / "assets" / "index-*.css")
    return sorted(pathlib.Path(p) for p in glob.glob(pat))


def rule_for(classes: list[str]) -> str:
    selectors = ",\n".join(f".{c}" for c in classes)
    return (
        f"\n/* {MARKER} — see docs/dsh-at-scale/97-client-per-window-cost.md */\n"
        f"{selectors} {{ contain: layout paint; }}\n"
    )


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, help="the DSH install root that holds node_modules")
    ap.add_argument("--check", action="store_true", help="report only; exit 1 when the rule is missing")
    args = ap.parse_args(argv)

    root = pathlib.Path(args.root)
    found = bundles(root)
    if not found:
        print(f"absent   no index-*.css under {root}/node_modules/@deepseek-ai/dsh-web-frontend/dist/assets")
        return 4

    rc = 0
    for b in found:
        text = b.read_text(encoding="utf-8", errors="surrogateescape")
        if MARKER in text:
            print(f"already-patched {b.name}")
            continue
        classes = sorted(set(CLASS_RE.findall(text)))
        if not classes:
            print(f"absent   {b.name}: no ._spinner*_<hash>_<n> class in the bundle — the spinner markup moved; re-author this patcher")
            rc = 4
            continue
        if args.check:
            print(f"missing  {b.name}: {len(classes)} spinner class(es) uncontained")
            rc = 1
            continue
        b.write_text(text + rule_for(classes), encoding="utf-8", errors="surrogateescape")
        print(f"patched  {b.name}: contain: layout paint on {len(classes)} spinner class(es)")
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
