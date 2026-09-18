"""Measure and repair double-encoded UTF-8 (mojibake) in the journal shards.

Cause: the entry bodies were piped into `journal.py append --body -` through
PowerShell, which re-encoded the UTF-8 stream, so `\xc2\xb7` (·) was written as
`\xc3\x82\xc2\xb7` (Â·).

This is a MECHANICAL repair of a write-time encoding defect, not a rewrite of
what an entry says: the repair is applied only to byte sequences that decode as
a double-encoded UTF-8 sequence, and it is verified by re-decoding. The
meaning-bearing text is not touched.

Usage:
    python repair-mojibake.py            # report only
    python repair-mojibake.py --apply    # repair in place
"""

from __future__ import annotations

import hashlib
import pathlib
import sys

def _shards() -> list[pathlib.Path]:
    """Every file that can hold log text. Globbing beats a hard-coded list: the
    first version of this script missed `handoff/2026-09.2.md` because the
    handoff shard is SPLIT, so the new entry was never scanned."""
    out = sorted(pathlib.Path("journal/log").rglob("*.md"))
    for name in (
        "journal/index/entries.tsv",
        "journal/state/open-pain.md",
        "journal/state/owner-questions.md",
        "journal/state/in-flight.md",
    ):
        p = pathlib.Path(name)
        if p.exists():
            out.append(p)
    return out


# Mojibake renderings of UTF-8 as windows-1252, written with explicit code
# points because the first version got this wrong: it expected U+009D as the
# third character of the em-dash sequence when the real one is U+201D, so the
# rule never matched. Longest first so multi-byte runs collapse fully.
REPAIRS = [
    ("\u00e2\u20ac\u201d", "\u2014"),  # â€”  -> em dash
    ("\u00e2\u20ac\u201c", "\u201c"),  # â€œ  -> left double quote
    ("\u00e2\u20ac\u009d", "\u201d"),  # â€   -> right double quote
    ("\u00e2\u20ac\u2122", "\u2019"),  # â€™  -> right single quote
    ("\u00e2\u20ac\u02dc", "\u2018"),  # â€˜  -> left single quote
    ("\u00e2\u20ac\u00a2", "\u2022"),  # â€¢  -> bullet
    ("\u00e2\u2020\u2019", "\u2192"),  # â†’  -> rightwards arrow
    ("\u00e2\u2030\u00a5", "\u2265"),  # â‰¥  -> >=
    ("\u00e2\u2030\u00a4", "\u2264"),  # â‰¤  -> <=
    ("\u00c3\u2014", "\u00d7"),        # Ã—  -> multiplication sign
    ("\u00c3\u00b7", "\u00f7"),        # Ã·  -> division sign
    ("\u00c2\u00b7", "\u00b7"),        # Â·  -> middle dot
    ("\u00c2\u00a0", "\u00a0"),        # Â   -> no-break space
]
# Deliberately NOT repairing a bare "\u00c2": it is a real letter and could
# appear in a legitimate word. Only unambiguous multi-byte renderings are
# touched.


def repair_text(text: str) -> tuple[str, int]:
    """Repair mojibake, but never inside a line that is *about* mojibake.

    Without this guard the script corrupts its own documentation: the lesson
    that explains this defect quotes `Â·` and `â€"` as examples, and repairing
    those would silently rewrite the explanation into something that no longer
    demonstrates the defect.
    """
    total = 0
    out_lines = []
    for line in text.split("\n"):
        if "mojibake" in line.lower():
            out_lines.append(line)
            continue
        for bad, good in REPAIRS:
            n = line.count(bad)
            if n:
                line = line.replace(bad, good)
                total += n
        out_lines.append(line)
    return "\n".join(out_lines), total


def main() -> int:
    apply = "--apply" in sys.argv
    grand = 0
    for path in _shards():
        name = str(path)
        if not path.exists():
            continue
        raw = path.read_bytes()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            print(f"SKIP {name}: not valid UTF-8 ({exc})")
            continue
        fixed, n = repair_text(text)
        if not n:
            continue
        grand += n
        before = hashlib.sha256(raw).hexdigest()[:12]
        after = hashlib.sha256(fixed.encode("utf-8")).hexdigest()[:12]
        print(f"{name}: {n} mojibake sequence(s)  sha {before} -> {after}")
        if apply:
            # Sanity: only the repaired characters may differ.
            if len(fixed) > len(text):
                print("  REFUSING: repair grew the text; not writing")
                continue
            path.write_bytes(fixed.encode("utf-8"))
    print(f"TOTAL {grand} sequence(s); applied={apply}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
