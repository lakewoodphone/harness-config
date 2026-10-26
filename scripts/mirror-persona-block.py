"""Mirror ONE persona rule from its source of truth into every surface that copies it.

WHY THIS EXISTS
`scripts/make_zabz_preset.py` is the source of truth for the persona, and
`presets/zabz/agent.cordis.yml` is generated from it. But the same text is HAND-COPIED into
two more committed files —

    profiles/web/cordis.patch.yml           (indent 30) — the profile layer the engine loads
    profiles/web/presets.generated.patch.yml (indent 30) — the staging copy of the same layer
    scripts/evolution/r6-rules-v6.py        (indent 9)  — the rule-book emitter

— and a rule corrected in one of them is silently still stated, wrongly, in the other two.
That is `AGENTS.md` §6.3's defect: a rule in one surface is not a rule. Measured 2026-10-26:
the persona's rule 8 ("it does not tell you when either happened") was false, was corrected in
the generator, and survived in all three copies until this script ran.

WHAT IT DOES
Reads the rule block out of `make_zabz_preset.py`, finds the corresponding block in each
target by its first line, and replaces it in place, preserving each file's own indentation.
It refuses rather than guesses: a target with zero matches or more than one match is an error,
because a wrong edit here rewrites a persona that six machines load.

The durable fix is for those two profile files to be GENERATED from the preset rather than
copied by hand; until they are, run this after any edit to rule text and check it with
`make_zabz_preset.py --check`.

    python scripts/mirror-persona-block.py --rule 8            # write
    python scripts/mirror-persona-block.py --rule 8 --check    # verify only, write nothing
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SOURCE = REPO / "scripts" / "make_zabz_preset.py"
TARGETS = [
    REPO / "profiles" / "web" / "cordis.patch.yml",
    REPO / "profiles" / "web" / "presets.generated.patch.yml",
    REPO / "scripts" / "evolution" / "r6-rules-v6.py",
]


def source_block(rule: str) -> list[str]:
    """The rule's lines from PERSONA in the generator, unindented, no trailing blanks."""
    text = SOURCE.read_text(encoding="utf-8")
    start = text.find(f"**{rule}. ")
    if start < 0:
        raise SystemExit(f"source: no rule **{rule}. found in {SOURCE}")
    end = text.find("**", start + 4)
    # The block ends at the next rule heading; there is none after the last rule.
    next_rule = re.search(r"\n\n\*\*\d+[a-z]?\. ", text[start:])
    if next_rule is not None:
        end = start + next_rule.start() + 2
    else:
        end = len(text)
    block = text[start:end].strip("\n")
    return [line.rstrip() for line in block.splitlines()]


def replace_in(path: Path, rule: str, block: list[str], check: bool) -> str:
    """Replace the rule block in one target. Returns 'ok' | 'would-write' | 'unchanged'."""
    raw = path.read_text(encoding="utf-8")
    lines = raw.splitlines()
    needle = f"**{rule}. "
    starts = [i for i, line in enumerate(lines) if needle in line]
    if len(starts) == 0:
        raise SystemExit(f"{path.name}: no rule **{rule}. found — refusing to guess")
    if len(starts) > 1:
        raise SystemExit(f"{path.name}: rule **{rule}. appears {len(starts)} times — refusing to guess which one")
    first = starts[0]
    indent = lines[first][: len(lines[first]) - len(lines[first].lstrip())]
    # The block ends on the line that closes the measured citation.
    last = None
    for i in range(first, min(first + 40, len(lines))):
        if lines[i].rstrip().endswith((")*", ")*'", ")*\"", ".)*")):
            last = i
            break
    if last is None:
        raise SystemExit(f"{path.name}: rule **{rule}. has no closing citation line within 40 lines — refusing to guess")
    replacement = [indent + line if line else indent.rstrip() for line in block]
    new_lines = lines[:first] + replacement + lines[last + 1 :]
    if new_lines == lines:
        return "unchanged"
    if check:
        return "would-write"
    path.write_text("\n".join(new_lines) + ("\n" if raw.endswith("\n") else ""), encoding="utf-8")
    return "ok"


def label(path: Path) -> str:
    """Repo-relative when possible; the absolute path otherwise (a --target may be outside the repo)."""
    try:
        return str(path.relative_to(REPO))
    except ValueError:
        return str(path)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rule", default="8")
    parser.add_argument("--check", action="store_true")
    parser.add_argument(
        "--target",
        action="append",
        default=None,
        metavar="PATH",
        help="Extra surface to mirror into (repeatable). The DEPLOYED profile patch is one: "
             "$DSH_HOME/profiles/web/cordis.patch.yml is NOT a copy of this repo's — measured "
             "2026-10-26 it had diverged by 1885/871 lines and still carried the old rule.",
    )
    args = parser.parse_args(argv)

    targets = list(TARGETS) + [Path(p) for p in (args.target or [])]
    block = source_block(args.rule)
    print(f"source {SOURCE.name}: rule **{args.rule}. — {len(block)} line(s)")
    stale = 0
    for target in targets:
        if not target.exists():
            print(f"  {label(target)}: MISSING (skipped)")
            continue
        result = replace_in(target, args.rule, block, args.check)
        if result in {"ok", "would-write"}:
            stale += 1
        print(f"  {label(target)}: {result}")
    if args.check:
        print(f"check: {stale} surface(s) differ from the source")
        return 1 if stale else 0
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
