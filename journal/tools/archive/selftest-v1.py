#!/usr/bin/env python3
"""selftest.py — the journal's format rules, tested on synthetic input.

Why this exists: on 2026-09-14 three separate silent failures came out of this format
(a body-only dedupe key, a single-line heading regex, and a glued marker after a
missing newline). Each was found by accident, after the data was already written.
These checks are cheap and run without touching the real journal:

    python tools/selftest.py

Every case below is a bug that actually happened, or the guard added for it.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from journal import (KINDS, MARKER_RE, body_hash, build_heading, content_key,  # noqa: E402
                     entry_hash, num_of, parse_legacy, suffix_of)

FAILS: list[str] = []


def check(name: str, got, want) -> None:
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"  (got {got!r}, want {want!r})"))
    if not ok:
        FAILS.append(name)


def main() -> int:
    print("markers")
    check("a well-formed marker parses",
          bool(MARKER_RE.match("<!-- e:pain|P46b|2026-09-14|ZABZ-YOGA|open -->")), True)
    check("a marker without a pipe is not a marker",
          bool(MARKER_RE.match("<!-- e:pain P46 -->")), False)
    check("a marker mid-line is not a marker",
          bool(MARKER_RE.match("x <!-- e:pain|P46|2026-09-14|h|open -->")), False)

    print("identity keys")
    # Eight old lessons (L23, L162-L166, L170, L173) put the whole lesson on the
    # heading line and have an EMPTY body. A body-only key made all eight identical
    # and seven were silently dropped. These two checks document the defect and the fix.
    a = ("**L23 · ps_health returns 90 KB**", "")
    b = ("**L162 · Production code can live outside version control**", "")
    check("the defect: two empty bodies hash the same", body_hash(a[1]) == body_hash(b[1]), True)
    check("the fix: the entry key includes the heading", entry_hash(*a) != entry_hash(*b), True)
    check("the fix holds in the migration's own key", content_key(*a) != content_key(*b), True)
    check("a non-empty body still identifies an entry",
          content_key("**P46 — x**", "Body text here.") == content_key("**P46b — x**", "Body text here."), True)

    print("headings")
    check("pain heading carries the id once",
          build_heading("pain", "P46b", "New title", "2026-09-14", "H"), "## P46b — New title")
    check("lesson heading carries the id once",
          build_heading("lessons", "L179", "Rule", "2026-09-14", "H"), "**L179 · Rule**")
    check("decision heading carries the id and date",
          build_heading("decisions", "D55", "Choice", "2026-09-14", "H"), "**D55 · 2026-09-14 · Choice.**")
    check("a handoff heading carries a timestamp",
          build_heading("handoff", "H68", "Title", "2026-09-14 06:10 UTC", "ZABZ-YOGA"),
          "## 2026-09-14 06:10 UTC · ZABZ-YOGA · Title")

    print("ids")
    check("num_of reads the number", num_of("P46b"), 46)
    check("suffix_of reads the suffix", suffix_of("P46b"), "b")
    check("a plain id has no suffix", suffix_of("P46"), "")

    print("legacy parsing")
    sample = (
        "# SAMPLE\n\n"
        "## P1 — First problem\n\nSymptom one.\n\n"
        "## P2 — Second problem\n\nSymptom two.\n\n---\n\n"
        "**L1 · A rule whose heading is long enough that the old file\nwrapped it onto a second line.** The body.\n\n"
        "*Learned:* evidence.\n"
    )
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "SAMPLE.md"
        p.write_text(sample, encoding="utf-8")
        pains = parse_legacy(p, "pain")
        check("two pain entries found", [e["id_full"] for e in pains], ["P1", "P2"])
        with tempfile.TemporaryDirectory() as td2:
            q = Path(td2) / "LESSONS.md"
            q.write_text(sample, encoding="utf-8")
            les = parse_legacy(q, "lessons")
            check("one lesson found", len(les), 1)
            check("its wrapped heading is whole",
                  les[0]["heading"].endswith("second line.**"), True)
            check("the text after the closing ** is body, not heading",
                  les[0]["body"].startswith("The body."), True)
            check("the lesson body keeps its own paragraphs",
                  "*Learned:* evidence." in les[0]["body"], True)

    print("kind table")
    check("five kinds", sorted(KINDS), ["decisions", "handoff", "lessons", "pain", "wins"])
    check("letters are distinct", len({v["letter"] for v in KINDS.values()}), 5)

    print()
    if FAILS:
        print(f"{len(FAILS)} FAILED: {', '.join(FAILS)}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
