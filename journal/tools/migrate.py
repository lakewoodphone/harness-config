#!/usr/bin/env python3
"""migrate.py — one-off: the six flat files -> sharded log + markers + stable ids.

Run once, on 2026-09-14, from the journal root:

    python tools/migrate.py

It reads the flat files from every machine that has a copy (the local checkout
plus any staged copies under _journal-merge/), takes the UNION of entries, drops
entries whose body is byte-identical after whitespace normalisation, and writes
journal/log/<kind>/<YYYY-MM>.md with a marker line per entry.

Numbering: a legacy number that appears on more than one entry is repaired as
P46 / P46b / P46c ordered by date, because P46 genuinely meant three different
problems and pretending otherwise hides the ambiguity. Cross-references in old
bodies are left verbatim; index/entries.tsv is the authority on what exists.

Nothing here deletes anything: the originals are moved to archive/ afterwards.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from journal import (JOURNAL, KINDS, LOG, build_heading, entry_hash, num_of,  # noqa: E402
                     parse_legacy)

MIGRATION_MONTH = "2026-09"
STAGE = Path.home() / "code" / "_journal-merge"

SOURCES = [
    ("yoga", "HANDOFF", JOURNAL / "HANDOFF.md"),
    ("yoga", "LESSONS", JOURNAL / "LESSONS.md"),
    ("yoga", "PAIN", JOURNAL / "PAIN.md"),
    ("yoga", "DECISIONS", JOURNAL / "DECISIONS.md"),
    ("yoga", "WINS", JOURNAL / "WINS.md"),
    ("tech", "HANDOFF", STAGE / "HANDOFF.tech.md"),
    ("tech", "LESSONS", STAGE / "LESSONS.tech.md"),
    ("tech", "PAIN", STAGE / "PAIN.tech.md"),
    ("tech", "DECISIONS", STAGE / "DECISIONS.tech.md"),
    ("tech", "WINS", STAGE / "WINS.tech.md"),
    ("secratary", "HANDOFF", STAGE / "HANDOFF.secratary.md"),
    ("secratary", "LESSONS", STAGE / "LESSONS.secratary.md"),
    ("secratary", "PAIN", STAGE / "PAIN.secratary.md"),
    ("secratary", "DECISIONS", STAGE / "DECISIONS.secratary.md"),
    ("secratary", "WINS", STAGE / "WINS.secratary.md"),
    ("stray", "PAIN", Path.home() / "code" / "PAIN.md"),
    ("stray", "DECISIONS", Path.home() / "code" / "DECISIONS.md"),
]

KIND_OF = {"HANDOFF": "handoff", "LESSONS": "lessons", "PAIN": "pain", "DECISIONS": "decisions", "WINS": "wins"}

DONE_RE = re.compile(r"(?im)^\*{0,2}(DONE|FIXED|RESOLVED|CLOSED|SHIPPED)\b")
RETRACT_RE = re.compile(r"(?im)^\*{0,2}(RETRACTED|SUPERSEDED|WRONG)\b")


def status_of(body: str) -> str:
    if RETRACT_RE.search(body):
        return "retracted"
    if DONE_RE.search(body):
        return "done"
    return "open"


def strip_suffix(id_full: str) -> str:
    return re.sub(r"^([A-Z]+\d+).*$", r"\1", id_full or "")


DATE_SEG = re.compile(r"^\d{4}-\d{2}-\d{2}[^·]*·\s*")


def title_of(heading: str, kind: str) -> str:
    """Recover a bare title from an old heading, whatever shape it grew into."""
    h = heading.strip()
    if kind == "lessons":
        h = re.sub(r"^\*\*L\d+\s*·\s*", "", h)
    elif kind == "pain":
        h = re.sub(r"^##\s*P\d+\b", "", h).strip(" —–-")
    else:
        h = re.sub(r"^\*\*[DW]\d+[a-z]?\s*·\s*", "", h)
        h = DATE_SEG.sub("", h)
    h = h.strip().strip("*").strip()
    if h.endswith("."):
        h = h[:-1]
    return h or "(untitled)"


def main() -> int:
    collected: dict[str, list[dict]] = {k: [] for k in KINDS}
    per_source: dict[str, int] = {}
    seen_hash: set[tuple[str, str]] = set()

    for machine, label, path in SOURCES:
        kind = KIND_OF[label]
        if not path.exists():
            print(f"-- skip (absent): {machine}/{label} {path}")
            continue
        ents = parse_legacy(path, kind)
        keep = 0
        for e in ents:
            key = (kind, entry_hash(e["heading"], e["body"]))
            if key in seen_hash:
                continue          # already have this entry verbatim from another machine
            seen_hash.add(key)
            e["machine"] = machine
            collected[kind].append(e)
            keep += 1
        per_source[f"{machine}/{label}"] = (len(ents), keep)
        print(f"   {machine:<9} {label:<9} {len(ents):>4} parsed, {keep:>4} new")

    report = ["# Migration of the six flat files", "", f"Sources read: {len(per_source)}", "",
              "| source | entries | unique |", "|---|---|---|"]
    for k, (a, b) in per_source.items():
        report.append(f"| {k} | {a} | {b} |")

    total = 0
    for kind, entries in collected.items():
        # order: dated entries by date then id, undated by id, handoff by date
        entries.sort(key=lambda e: (e["date"] or MIGRATION_MONTH, num_of(e.get("id_full") or "") or 0))
        # stable id allocation with collision suffixes
        numbers: dict[int, int] = {}
        letters = "abcdefghij"
        for e in entries:
            if kind == "handoff":
                continue
            n = num_of(e.get("id_full") or "")
            seen = numbers.get(n, 0)
            numbers[n] = seen + 1
            e["id_full"] = KINDS[kind]["letter"] + str(n) + (letters[seen] if seen else "")
        # handoff ids H1..Hn in date order
        if kind == "handoff":
            for i, e in enumerate(entries, start=1):
                e["id_full"] = f"H{i}"

        shards: dict[str, list[dict]] = {}
        for e in entries:
            month = (e["date"] or MIGRATION_MONTH)[:7]
            if not re.match(r"^\d{4}-\d{2}$", month):
                month = MIGRATION_MONTH
            shards.setdefault(month, []).append(e)

        for month, ents in sorted(shards.items()):
            path = LOG / kind / f"{month}.md"
            path.parent.mkdir(parents=True, exist_ok=True)
            out = [f"# {kind} · {month}", "",
                   "<!-- journal shard: append-only, oldest first. Never edit an entry — correct it with an",
                   f"     entry that cites it. Reads: python tools/journal.py newest {kind} 3 -->", ""]
            section = None
            for e in ents:
                if e["section"] and e["section"] != section:
                    section = e["section"]
                    out.append(f"## {section}")
                    out.append("")
                date = e["date"] or ""
                host = e["host"] or "-"
                status = status_of(e["body"])
                out.append(f"<!-- e:{kind}|{e['id_full']}|{date}|{host}|{status} -->")
                if kind == "handoff":
                    out.append(e["heading"])
                else:
                    out.append(build_heading(kind, e["id_full"], title_of(e["heading"], kind),
                                             date or "2026-09-11", "migrated"))
                out.append("")
                out.append(e["body"])
                out.append("")
                out.append("---")
                out.append("")
                total += 1
            path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8", newline="\n")

        ids = [e["id_full"] for e in entries]
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        report += ["", f"## {kind}: {len(entries)} entries -> log/{kind}/" + "{"
                   + ", ".join(sorted(shards)) + "}", "", f"ids: {ids[0] if ids else '-'} .. {ids[-1] if ids else '-'}"
                   + (f" · repaired collisions: {', '.join(dupes)}" if dupes else "")]
        print(f"{kind:<10} {len(entries):>4} entries -> log/{kind}/ ({', '.join(sorted(shards))})")

    (JOURNAL / "archive").mkdir(exist_ok=True)
    (JOURNAL / "archive" / "MIGRATION.md").write_text("\n".join(report) + "\n", encoding="utf-8", newline="\n")
    print(f"\n{total} entries written. Report: journal/archive/MIGRATION.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
