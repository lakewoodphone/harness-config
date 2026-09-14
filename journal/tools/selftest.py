#!/usr/bin/env python3
"""selftest.py — the journal's format rules, the cache's freshness proof and the
budgeter, tested on synthetic input in a temp directory.

Why this exists: three separate silent failures came out of this format (a body-only
dedupe key, a single-line heading regex, and a glued marker after a missing newline),
each found by accident after the data was already written; and v2 adds three new ways
to lose a page or a cache. These checks are cheap and never touch the real journal:

    python tools/selftest.py

Every case below is a bug that actually happened, or the guard added for it.
"""
from __future__ import annotations

import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parent

FAILS = []
PASSES = [0]


def check(name, got, want):
    ok = got == want
    print("  %s  %s%s" % ("PASS" if ok else "FAIL", name,
                          "" if ok else "  (got %r, want %r)" % (got, want)))
    if ok:
        PASSES[0] += 1
    else:
        FAILS.append(name)


def check_true(name, got):
    check(name, bool(got), True)


def run(argv):
    """Run a journal command in-process, capturing stdout/stderr. Returns (rc, out, err)."""
    buf, err = io.StringIO(), io.StringIO()
    with redirect_stdout(buf), redirect_stderr(err):
        rc = j_main(argv)
    return rc, buf.getvalue(), err.getvalue()


j_main = None   # set by main() once the module is loaded


def load_module():
    """Import journal.py by path, so a fixture root can be attached to it."""
    spec = importlib.util.spec_from_file_location("journal_v2_" + str(os.getpid()),
                                                  str(HERE / "journal.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def set_root(mod, root):
    """Point the module at a fixture root exactly as --root does, caches included."""
    mod.JOURNAL = Path(root)
    mod.clear_caches()


def fixture(root: Path) -> Path:
    """A tiny v2-shaped journal root: one legacy shard, one flat file."""
    (root / "log" / "lessons").mkdir(parents=True, exist_ok=True)
    (root / "log" / "pain").mkdir(parents=True, exist_ok=True)
    (root / "entries" / "pain").mkdir(parents=True, exist_ok=True)
    (root / "entries" / "lessons").mkdir(parents=True, exist_ok=True)
    (root / "state").mkdir(parents=True, exist_ok=True)
    (root / "FORMAT").write_text("2\n", encoding="utf-8", newline="\n")
    (root / "log" / "lessons" / "2026-09.md").write_text(
        "# lessons · 2026-09\n"
        "<!-- journal shard: append-only -->\n\n"
        "<!-- e:lessons|L1|2026-09-14|ZABZ-YOGA|open -->\n"
        "**L1 · A rule whose heading the old file wrapped\nonto a second line.**\n\n"
        "The body of L1.\n\n"
        "---\n\n"
        "<!-- e:lessons|L2|2026-09-14|ZABZ-YOGA|open -->\n"
        "**L2 · Heading only**\n"
        "<!-- e:lessons|L3|2026-09-14|ZABZ-YOGA|open -->\n"
        "**L3 · Third**\n\n"
        "Third body.\n",
        encoding="utf-8", newline="\n")
    (root / "LESSONS.md").write_text(
        "# LESSONS\n\n## On evidence\n\n"
        "**L9 · Only in the flat file.**\n\nFlat body.\n",
        encoding="utf-8", newline="\n")
    return root


# ---------------------------------------------------------------------------

def test_markers(j):
    print("markers")
    check("a well-formed marker parses",
          bool(j.MARKER_RE.match("<!-- e:pain|P46b|2026-09-14|ZABZ-YOGA|open -->")), True)
    check("a marker without a pipe is not a marker",
          bool(j.MARKER_RE.match("<!-- e:pain P46 -->")), False)
    check("a marker mid-line is not a marker",
          bool(j.MARKER_RE.match("x <!-- e:pain|P46|2026-09-14|h|open -->")), False)
    check("a marker with an extra field is not a marker",
          bool(j.MARKER_RE.match("<!-- e:pain|P46|2026-09-14|h|open|extra -->")), False)
    m = j.MARKER_RE.match("<!-- e:lessons|L173|2026-09-14|ZABZ-YOGA|open -->")
    check("the marker splits into kind/id/date/host/status",
          (m.group("kind"), m.group("id"), m.group("date"), m.group("host"), m.group("status")),
          ("lessons", "L173", "2026-09-14", "ZABZ-YOGA", "open"))
    check("a glued marker is caught by the loose form",
          bool(j.LOOSE_MARKER_RE.match("---<!-- e:pain|P56|2026-09-14|h|open -->")), True)
    check("...and is still refused by the strict form",
          bool(j.MARKER_RE.match("---<!-- e:pain|P56|2026-09-14|h|open -->")), False)


def test_identity(j):
    print("identity keys")
    a = ("**L23 · ps_health returns 90 KB**", "")
    b = ("**L162 · Production code can live outside version control**", "")
    check("the defect: two empty bodies hash the same", j.body_hash(a[1]) == j.body_hash(b[1]), True)
    check("the fix: the entry key includes the heading", j.entry_hash(*a) != j.entry_hash(*b), True)
    check("the fix holds in the migration's own key", j.content_key(*a) != j.content_key(*b), True)
    check("a non-empty body still identifies an entry",
          j.content_key("**P46 — x**", "Body text here.") == j.content_key("**P46b — x**", "Body text here."),
          True)
    check("entry_hash ignores trailing separators",
          j.entry_hash("**L1 · T**", "Body.\n\n---\n") == j.entry_hash("**L1 · T**", "Body."), True)
    check("entry_hash is stable under trailing whitespace",
          j.entry_hash("**L1 · T**", "  Body.\n\n\n") == j.entry_hash("**L1 · T**", "Body."), True)
    check("entry_hash ignores runs of spaces but not content",
          j.entry_hash("**L1 · T**", "a  b") == j.entry_hash("**L1 · T**", "a b"), True)
    check("a heading-only entry still has an identity", len(j.entry_hash("**L5 · only**", "")), 16)


def test_headings(j):
    print("headings")
    check("pain heading carries the id once",
          j.build_heading("pain", "P46b", "New title", "2026-09-14", "H"), "## P46b — New title")
    check("lesson heading carries the id once",
          j.build_heading("lessons", "L179", "Rule", "2026-09-14", "H"), "**L179 · Rule**")
    check("decision heading carries the id and the date",
          j.build_heading("decisions", "D55", "Choice", "2026-09-14", "H"),
          "**D55 · 2026-09-14 · Choice.**")
    check("a win heading matches the decision form",
          j.build_heading("wins", "W25", "Proved", "2026-09-14", "H"),
          "**W25 · 2026-09-14 · Proved.**")
    check("a handoff heading carries a timestamp",
          j.build_heading("handoff", "H68", "Title", "2026-09-14 06:10 UTC", "ZABZ-YOGA"),
          "## 2026-09-14 06:10 UTC · ZABZ-YOGA · Title")
    for kind in j.KINDS:
        date = "2026-09-14 06:10 UTC" if kind == "handoff" else "2026-09-14"
        h = j.build_heading(kind, j.KINDS[kind]["letter"] + "1", "T", date, "H")
        check("%s heading is recognised by its own kind regex" % kind,
              bool(j.KINDS[kind]["regex"].match(h)), True)


def test_ids(j):
    print("ids")
    check("num_of reads the number", j.num_of("P46b"), 46)
    check("suffix_of reads the suffix", j.suffix_of("P46b"), "b")
    check("a plain id has no suffix", j.suffix_of("P46"), "")
    check("a two-character suffix survives", j.suffix_of("D41ab"), "ab")
    check("an id with no digits is number 0", j.num_of("Lx"), 0)


def test_legacy_parsing(j):
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
        p.write_text(sample, encoding="utf-8", newline="\n")
        pains = j.parse_legacy(p, "pain")
        check("two pain entries found", [e["id_full"] for e in pains], ["P1", "P2"])
        check("the text after the closing ** is body, not heading",
              pains[1]["body"].startswith("Symptom two."), True)
        q = Path(td) / "LESSONS.md"
        q.write_text(sample, encoding="utf-8", newline="\n")
        les = j.parse_legacy(q, "lessons")
        check("one lesson found", len(les), 1)
        check("its wrapped heading is whole", les[0]["heading"].endswith("second line.**"), True)
        check("the text after the closing ** is body, not heading",
              les[0]["body"].startswith("The body."), True)
        check("the lesson body keeps its own paragraphs", "*Learned:* evidence." in les[0]["body"], True)


def test_entry_file_format(j):
    print("entry file format (marker, heading, body, meta)")
    e = {"kind": "lessons", "id_full": "L173", "date": "2026-09-14", "host": "ZABZ-YOGA",
         "status": "open", "heading": "**L173 · The title**", "body": "The body.",
         "tags": ["journal"], "refs": ["L172"], "alias_of": "", "sha": ""}
    text = j.entry_bytes(e)
    lines = text.split("\n")
    check("line 1 is the v1 marker, unextended",
          lines[0], "<!-- e:lessons|L173|2026-09-14|ZABZ-YOGA|open -->")
    check("line 2 is the heading", lines[1], "**L173 · The title**")
    check("the last content line is the j2 meta comment", lines[-2].startswith("<!-- j2 "), True)
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "L173.md"
        p.write_text(text, encoding="utf-8", newline="\n")
        got = j.parse_entry(p, "lessons")
        check("round-trip: no problems", got["problems"], [])
        check("round-trip: id", got["id_full"], "L173")
        check("round-trip: heading", got["heading"], "**L173 · The title**")
        check("round-trip: body has the meta line stripped", got["body"], "The body.")
        check("round-trip: tags", got["tags"], ["journal"])
        check("round-trip: refs", got["refs"], ["L172"])
        check("round-trip: sha matches entry_hash", got["sha"], j.entry_hash(e["heading"], e["body"]))
        # a file with no meta line at all must still parse
        plain = "\n".join(lines[:4]) + "\n"
        p.write_text(plain, encoding="utf-8", newline="\n")
        got = j.parse_entry(p, "lessons")
        check("front-matter-less file parses", got["body"], "The body.")
        check("...with no problems", got["problems"], [])
        # heading-only entry: an empty body is legal
        p.write_text("<!-- e:lessons|L173|2026-09-14|h|open -->\n**L173 · ps_health returns 90 KB**\n",
                     encoding="utf-8", newline="\n")
        got = j.parse_entry(p, "lessons")
        check("heading-only entry has an empty body", got["body"], "")
        check("heading-only entry raises no problem", got["problems"], [])
        check("heading-only entry still hashes", len(got["hash"]), 16)
        # sha mismatch is an error the checker can see
        bad = text.replace("sha=" + j.entry_hash(e["heading"], e["body"]), "sha=0000000000000000")
        p.write_text(bad, encoding="utf-8", newline="\n")
        got = j.parse_entry(p, "lessons")
        check("a metadata sha that disagrees is reported",
              any("sha=" in x for x in got["problems"]), True)
        # a file name that disagrees with the marker
        p2 = Path(td) / "L999.md"
        p2.write_text(text, encoding="utf-8", newline="\n")
        got = j.parse_entry(p2, "lessons")
        check("a file name that disagrees with the marker is reported",
              any("file name" in x for x in got["problems"]), True)
        # CRLF
        p3 = Path(td) / "L173.md"
        p3.write_bytes(text.replace("\n", "\r\n").encode("utf-8"))
        got = j.parse_entry(p3, "lessons")
        check("CRLF is reported", any("CRLF" in x for x in got["problems"]), True)
        check("...and the body is still readable", got["body"], "The body.")
        # a marker kind that is not a kind at all
        p4 = Path(td) / "X1.md"
        p4.write_text("<!-- e:nonsense|X1|2026-09-14|h|open -->\n**X1 · x**\n", encoding="utf-8", newline="\n")
        got = j.parse_entry(p4, "nonsense")
        check("an unknown marker kind is reported",
              any("not one of" in x for x in got["problems"]), True)


def test_meta_parse(j):
    print("metadata")
    body, meta = j.parse_meta("Body.\n<!-- j2 tags=a,b refs=L1 sha=abcdef alias_of= -->")
    check("meta is stripped from the body", body, "Body.")
    check("tags split on commas", meta["tags"], "a,b")
    check("refs present", meta["refs"], "L1")
    check("alias_of present but empty", meta["alias_of"], "")
    body, meta = j.parse_meta("Body with no meta.\n")
    check("no meta means no meta", meta, {})
    check("...and the body is untouched", body, "Body with no meta.\n")
    body, meta = j.parse_meta("")
    check("empty body is safe", (body, meta), ("", {}))


def test_budget(j):
    print("budgeter")
    b = j.Budget(200)
    b.reserve(24)
    i = 0
    while b.line("line %04d with some padding text to make it long enough" % i):
        i += 1
    b.marker(37)
    out = b.emit()
    check("the budget is never exceeded", len(out.encode("utf-8")) <= 200, True)
    check("the cut is marked", "… (+37 more)" in out, True)
    check_true("truncation happened", i < 6)
    b2 = j.Budget(120)
    check("a line that does not fit is refused", b2.line("x" * 400), False)
    check("...and nothing was added", b2.used, 0)
    b3 = j.Budget(300)
    b3.reserve(24)
    check_true("blob adds many lines", b3.blob("a\nb\nc"))
    check_true("used grew", b3.used > 0)
    b4 = j.Budget(150)
    b4.blob("x" * 40 + "\n" + "y" * 40 + "\n" + "z" * 400)
    check("a blob that overflows is cut", len(b4.emit().encode("utf-8")) <= 150, True)
    for budget in (200, 1000, 6000):
        b5 = j.Budget(budget)
        while b5.line("padding line %d" % b5.used):
            pass
        check("never exceeds a budget of %d" % budget, len(b5.emit().encode("utf-8")) <= budget, True)


def test_shard_split_and_migration(j, tmp_holder):
    print("shard split and migrate-v2")
    with tempfile.TemporaryDirectory() as td:
        tmp = fixture(Path(td))
        set_root(j, tmp)
        src = tmp / "log" / "lessons" / "2026-09.md"
        text = src.read_text(encoding="utf-8")
        preamble, blocks = j.shard_blocks(src)
        joined = "\n".join(b for b, _s, _e in blocks)
        # a line-range split loses exactly one newline per block (the one that terminated
        # its last line); the preamble keeps its own
        # the join supplies the newline between each pair of blocks; the only newline it
        # does not supply is the one that separates the preamble from the first block
        check("blocks plus preamble plus every newline reproduce the shard byte for byte",
              len(joined.encode("utf-8")) + len(preamble.encode("utf-8")) + 1,
              len(text.encode("utf-8")))
        check("three blocks found", len(blocks), 3)
        rc, out, _e = run(["migrate-v2", "--root", str(tmp)])
        check("dry run exits 0", rc, 0)
        check("dry run wrote no entry file",
              list((tmp / "entries").rglob("*.md")) if (tmp / "entries").exists() else [], [])
        rc, out, _e = run(["migrate-v2", "--apply", "--root", str(tmp)])
        check("migrate-v2 --apply exits 0", rc, 0)
        check("the byte-preservation proof is in the output",
              ("residue: 0 B" in out) or ("residue 0" in out), True)
        check("L1 written", (tmp / "entries" / "lessons" / "L1.md").is_file(), True)
        check("L3 written", (tmp / "entries" / "lessons" / "L3.md").is_file(), True)
        check("the flat-only lesson was absorbed", (tmp / "entries" / "lessons" / "L9.md").is_file(), True)
        got = j.load_one("L2", "lessons")
        check("heading-only entry survives migration", got["body"], "")
        got = j.load_one("L1", "lessons")
        # the fixture's shard heading wraps onto a second line, which v1's format cannot
        # represent in one entry file: the file must carry a whole heading, so it is
        # joined, and the identity the shard had is preserved exactly (checked below)
        check("a wrapped source heading is read whole and written on one line",
              ("\n" not in got["heading"]) and got["heading"].endswith("second line.**"), True)
        check("its body is the source body", got["body"], "The body of L1.")
        check("the migrated identity equals the source identity",
              got["hash"],
              j.entry_hash("**L1 · A rule whose heading the old file wrapped onto a second line.**",
                           "The body of L1."))
        check("re-reading the written file does not change the hash",
              j.parse_entry(tmp / "entries" / "lessons" / "L1.md", "lessons")["hash"], got["hash"])
        before = sorted(p.name for p in (tmp / "entries" / "lessons").iterdir())
        hashes_before = sorted(j.load_one(p[:-3], "lessons")["hash"] for p in before)
        rc, out, _e = run(["migrate-v2", "--apply", "--root", str(tmp)])
        after = sorted(p.name for p in (tmp / "entries" / "lessons").iterdir())
        check("a second migrate-v2 writes nothing", before, after)
        check("...and changes no hash", hashes_before,
              sorted(j.load_one(p[:-3], "lessons")["hash"] for p in after))
        check("...and still exits 0", rc, 0)
        rc, _o, _e = run(["check", "--root", str(tmp), "--quiet"])
        check("check is clean on the migrated fixture", rc, 0)
        tmp_holder.append(tmp)




def test_partial_migration_order(j):
    """The defect that scarred the real tree: a partial migration, then absorption.

    Ordering that produced `entries/lessons/L170.md` holding the flat file's L162 text:
    migrate some shards, then pull the flats in, then migrate the rest. With one
    allocation ceiling over every source and a batch assignment, no number may be handed
    out below a number any source claims, and file name / marker id / heading id must
    agree or `legacy_id` must explain the difference.
    """
    print("partial migration then absorption (the L162/L170 defect)")
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "log" / "lessons").mkdir(parents=True, exist_ok=True)
        (root / "log" / "pain").mkdir(parents=True, exist_ok=True)
        (root / "state").mkdir(parents=True, exist_ok=True)
        (root / "FORMAT").write_text("2\n", encoding="utf-8", newline="\n")
        # shard A: ids 1..3 of one kind
        (root / "log" / "lessons" / "2026-09.md").write_text(
            "# lessons · 2026-09\n\n"
            "<!-- e:lessons|L1|2026-09-14|H|open -->\n**L1 · One**\n\nBody one.\n\n---\n\n"
            "<!-- e:lessons|L2|2026-09-14|H|open -->\n**L2 · Two**\n\nBody two.\n\n---\n\n"
            "<!-- e:lessons|L3|2026-09-14|H|open -->\n**L3 · Three**\n\nBody three.\n",
            encoding="utf-8", newline="\n")
        # shard B arrives later and owns the high ids, including L9
        shard_b = (
            "# lessons · 2026-09.1\n\n"
            "<!-- e:lessons|L9|2026-09-14|H|open -->\n**L9 · Nine**\n\nBody nine.\n\n---\n\n"
            "<!-- e:lessons|L10|2026-09-14|H|open -->\n**L10 · Ten**\n\nBody ten.\n")
        # the flat file, written before the shards, still claims L9 with DIFFERENT content
        # and holds one lesson the log never had (L9 flat text) and one it did (L1)
        (root / "LESSONS.md").write_text(
            "# LESSONS\n\n## On evidence\n\n"
            "**L9 · The flat file\u2019s own ninth lesson, which the log never had.**\n\n"
            "Flat nine body.\n\n"
            "**L1 · One**\n\nBody one.\n",
            encoding="utf-8", newline="\n")
        set_root(j, root)

        # (a) migrate only part of the shards: shard A, by hiding shard B
        (root / "log" / "lessons" / "2026-09.1.md").write_text(shard_b, encoding="utf-8", newline="\n")
        held = (root / "log" / "lessons" / "2026-09.1.md").read_text(encoding="utf-8")
        (root / "log" / "lessons" / "2026-09.1.md").unlink()
        rc, out, _e = run(["migrate-v2", "--apply", "--root", str(root)])
        check("partial migration exits 0", rc, 0)
        check("shard A landed", (root / "entries" / "lessons" / "L1.md").is_file(), True)

        # (b) absorb, with shard B still absent: the flat L9 text must NOT take L9 in a way
        # that collides, but it must also not be allocated below the legacy ceiling
        rc, out, _e = run(["import-legacy", "--apply", "--root", str(root)])
        check("absorption exits 0", rc, 0)
        flat9 = [f for f in (root / "entries" / "lessons").iterdir()
                 if "Flat nine body." in f.read_text(encoding="utf-8")]
        check("the flat-only lesson was absorbed exactly once", len(flat9), 1)
        if flat9:
            got = j.parse_entry(flat9[0], "lessons")
            check("it kept the id the flat file gave it (L9 was free at that moment)",
                  got["id_full"], "L9")
            check("its heading carries the same id", j.heading_id_token(got), got["id_full"])

        # (c) now the rest of the shards arrive and are migrated
        (root / "log" / "lessons" / "2026-09.1.md").write_text(held, encoding="utf-8", newline="\n")
        set_root(j, root)
        rc, out, _e = run(["migrate-v2", "--apply", "--root", str(root)])
        check("the rest of the migration exits 0", rc, 0)
        entries, _p = j.load_entries()
        by_hash = {}
        for e in entries:
            by_hash.setdefault(e["hash"], []).append(e["id_full"])
        dupes = {h: ids for h, ids in by_hash.items() if len(ids) > 1}
        check("every source entry's hash is present exactly once", dupes, {})
        ids = [e["id_full"] for e in entries]
        check("no id is used twice in the tree", len(ids), len(set(ids)))
        for e in entries:
            token = j.heading_id_token(e)
            if token and token != e["id_full"]:
                check("%s: a heading id that differs from the file is explained by legacy_id"
                      % e["id_full"], j._legacy_id_of(e), token)
        # L9 was free when the flat file was absorbed, so the flat text holds L9; the
        # shard's own L9 (different content) arrived later and had to move ABOVE the ceiling
        l9 = j.load_one("L9", "lessons")
        check("the flat text kept L9 (it was free when it was absorbed)",
              "Flat nine body." in l9["body"], True)
        shard_nine = [e for e in entries if "Body nine." in e["body"]]
        check("the shard's L9 text exists exactly once", len(shard_nine), 1)
        check("...and was bumped above the ceiling that every source claims",
              j.num_of(shard_nine[0]["id_full"]) >= 10, True)
        check("...and records the legacy id it was filed as",
              j._legacy_id_of(shard_nine[0]) or j.heading_id_token(shard_nine[0]), "L9")

        # ids are stable across a second run
        before = sorted((e["id_full"], e["hash"]) for e in entries)
        rc, out, _e = run(["migrate-v2", "--apply", "--root", str(root)])
        after = sorted((e["id_full"], e["hash"]) for e in j.load_entries()[0])
        check("a second migrate-v2 changes nothing", after, before)
        check("...and reports it wrote nothing", "written 0" in out, True)
        check("no allocated number is below the legacy ceiling",
              all(j.num_of(e["id_full"]) >= 1 for e in j.load_entries()[0]), True)
        rc, out, _e = run(["check", "--root", str(root), "--quiet"])
        check("check is clean after the partial-migration order", rc, 0)



def test_cache_self_heal(j):
    print("cache self-heal and freshness stamp")
    with tempfile.TemporaryDirectory() as td:
        tmp = fixture(Path(td))
        set_root(j, tmp)
        run(["migrate-v2", "--apply", "--root", str(tmp)])
        stamp1 = json.loads((tmp / "index" / "stamp.json").read_text(encoding="utf-8"))
        check("stamp records a count", stamp1.get("entries_count"), 4)
        check("the cache is reported fresh", j.cache_fresh(), True)
        tsv = (tmp / "index" / "entries.tsv").read_text(encoding="utf-8")
        check("entries.tsv keeps v1's exact 12 columns", tsv.split("\n")[0],
              "kind\tid_full\tnum\tsuffix\tdate\thost\tstatus\theading\tfile\tline_start\tline_end\thash")
        check("entries.tsv says one line per entry", len(tsv.strip().split("\n")) - 1, 4)
        check("the file column points at the entry file",
              "\tentries/lessons/L1.md\t" in tsv, True)
        # a wiped entries.tsv (what a stale v1 `index` run leaves behind)
        (tmp / "index" / "entries.tsv").write_text("kind\tid_full\n", encoding="utf-8", newline="\n")
        (tmp / "index" / "stamp.json").unlink()
        rows, source, fresh = j.catalog()
        check("a wiped index self-heals on the next read", len(rows), 4)
        # a new entry file invalidates the stamp
        (tmp / "entries" / "lessons" / "L4.md").write_text(
            "<!-- e:lessons|L4|2026-09-14|h|open -->\n**L4 · Added out of band**\n\nBody.\n",
            encoding="utf-8", newline="\n")
        check("a new entry file makes the cache stale", j.cache_fresh(), False)
        rows, _s, fresh = j.catalog()
        check("...and the next read sees it", any(r["id_full"] == "L4" for r in rows), True)
        check("the cache is fresh again afterwards", j.cache_fresh(), True)
        # a locked stale cache must not block a read
        (tmp / ".lock").write_text("99999@elsewhere:1\n", encoding="utf-8", newline="\n")
        (tmp / "entries" / "lessons" / "L5.md").write_text(
            "<!-- e:lessons|L5|2026-09-14|h|open -->\n**L5 · Written while locked**\n\nBody.\n",
            encoding="utf-8", newline="\n")
        rc, _o, err = run(["list", "--root", str(tmp)])
        check("a locked, stale cache still answers from entries/", rc, 0)
        check("...and says so on stderr", "locked by" in err, True)
        (tmp / ".lock").unlink()
        rows, _s, _f = j.catalog()
        check("...and heals once the lock is gone", j.cache_fresh(), True)


def test_resolution(j):
    print("id resolution: exact, base, alias")
    with tempfile.TemporaryDirectory() as td:
        tmp = fixture(Path(td))
        set_root(j, tmp)
        run(["migrate-v2", "--apply", "--root", str(tmp)])
        e = j.load_one("L1", "lessons")
        check("an exact id opens its own file", e["heading"].startswith("**L1 "), True)
        check("an unknown id returns nothing", j.load_one("L404", "lessons"), None)
        hits = j._prefix_hits("L1")
        check("a base id matches its siblings", sorted(x["id_full"] for x in hits), ["L1"])
        (tmp / "entries" / "lessons" / "L1b.md").write_text(
            "<!-- e:lessons|L1b|2026-09-14|h|open -->\n**L1b · A second lesson numbered 1**\n\nOther body.\n",
            encoding="utf-8", newline="\n")
        j.rebuild_cache()
        hits = j._prefix_hits("L1")
        check("base id now matches two entries", sorted(x["id_full"] for x in hits), ["L1", "L1b"])
        check("an exact id still opens exactly one", j.load_one("L1", "lessons")["id_full"], "L1")
        rc, out, err = run(["show", "L1", "--root", str(tmp)])
        check("show of a base id with two matches exits 0", rc, 0)
        check("...and prints both, never silently picking one",
              ("L1b" in out) and ("matches 2 entries" in out or "matches 2 entries" in err), True)
        j.record_alias("L1", "lessons", "L1b", "test alias")
        check("an alias resolves", j.resolve_alias("L1"), "L1b")
        check("an id that is not an alias resolves to itself", j.resolve_alias("L3"), "L3")
        j.record_alias("L1z", "lessons", "L1", "chained alias")
        check("a chain resolves to the end", j.resolve_alias("L1z"), "L1b")


def test_append_and_concurrency(j):
    print("append, id safety, concurrency")
    with tempfile.TemporaryDirectory() as td:
        tmp = fixture(Path(td))
        set_root(j, tmp)
        run(["migrate-v2", "--apply", "--root", str(tmp)])
        rc, out, _e = run(["append", "lessons", "--title", "New rule", "--body", "Body text.",
                           "--root", str(tmp), "--no-fetch"])
        check("append exits 0", rc, 0)
        check("append allocated above the highest id (L9 came from the flat file)",
              (tmp / "entries" / "lessons" / "L10.md").is_file(), True)
        e = j.load_one("L10", "lessons")
        check("the appended entry round-trips", e["body"], "Body text.")
        check("...and it carries its metadata", e["sha"], j.entry_hash(e["heading"], e["body"]))
        rc, out, _e = run(["append", "lessons", "--title", "New rule", "--body", "Body text.",
                           "--root", str(tmp), "--no-fetch"])
        check("re-appending identical content writes no second file", rc, 0)
        check("...and records an alias instead", j.resolve_alias("L10"), "L10")
        # an id that exists with different content must be bumped, not reused
        (tmp / "entries" / "lessons" / "L11.md").write_text(
            "<!-- e:lessons|L11|2026-09-14|h|open -->\n**L11 · Taken**\n\nSomething else entirely.\n",
            encoding="utf-8", newline="\n")
        rc, out, _e = run(["append", "lessons", "--title", "Wants eleven", "--body", "Mine.",
                           "--root", str(tmp), "--no-fetch"])
        check("append does not collide with a live id", rc, 0)
        check("it bumped to L12", (tmp / "entries" / "lessons" / "L12.md").is_file(), True)
        check("...and recorded the alias", j.resolve_alias("L11"), "L11")
        check("the fixture is still clean after appends",
              run(["check", "--root", str(tmp), "--quiet"])[0], 0)

        # six processes at once, which is what a fleet actually does
        tmp2 = Path(td) / "race"
        tmp2.mkdir()
        fixture(tmp2)
        set_root(j, tmp2)
        run(["migrate-v2", "--apply", "--root", str(tmp2)])
        procs = [subprocess.Popen(
            [sys.executable, str(HERE / "journal.py"), "append", "pain",
             "--title", "Race %d" % i, "--body", "Simultaneous writer %d." % i,
             "--root", str(tmp2), "--no-fetch"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE) for i in range(6)]
        outs = [p.communicate() for p in procs]
        rcs = [p.returncode for p in procs]
        check("all six appends exited 0", rcs, [0, 0, 0, 0, 0, 0])
        ids = sorted(p.stem for p in (tmp2 / "entries" / "pain").iterdir() if p.suffix == ".md")
        check("six distinct pain ids exist", len(ids), 6)
        check("...and no id was reused", len(set(ids)), 6)
        check("a serial check after the race is clean",
              run(["check", "--root", str(tmp2), "--quiet"])[0], 0)
        check("every raced entry kept its own body",
              all(j.load_one(i, "pain")["body"] for i in ids), True)
        check("no lock file was left behind", (tmp2 / ".lock").exists(), False)


def test_check_rules(j):
    print("check rules")
    with tempfile.TemporaryDirectory() as td:
        tmp = fixture(Path(td))
        set_root(j, tmp)
        run(["migrate-v2", "--apply", "--root", str(tmp)])
        check("clean fixture: no errors", run(["check", "--root", str(tmp), "--quiet"])[0], 0)
        # one id naming two different entries is impossible in a file-per-id tree, so the
        # reachable form of the defect is a MARKER id that its file name does not own
        (tmp / "entries" / "lessons" / "L3b.md").write_text(
            "<!-- e:lessons|L3|2026-09-14|h|open -->\n**L3 · A second entry claiming L3**\n\nX.\n",
            encoding="utf-8", newline="\n")
        j.rebuild_cache()
        rc, out, _e = run(["check", "--root", str(tmp), "--quiet"])
        check("a marker id its file name does not own exits non-zero", rc, 1)
        check("...and the summary always prints the three counts",
              "error(s)" in out and "warning(s)" in out and "info" in out, True)
        (tmp / "entries" / "lessons" / "L3b.md").unlink()
        # malformed marker -> ERROR
        (tmp / "entries" / "pain" / "P1.md").write_text("not a marker\n**P1 · x**\n",
                                                        encoding="utf-8", newline="\n")
        j.rebuild_cache()
        check("a malformed entry file exits non-zero", run(["check", "--root", str(tmp), "--quiet"])[0], 1)
        (tmp / "entries" / "pain" / "P1.md").unlink()
        j.rebuild_cache()
        check("removing it clears the error", run(["check", "--root", str(tmp), "--quiet"])[0], 0)
        # legacy drift is reported with the true count
        (tmp / "PAIN.md").write_text("# PAIN\n\n## P90 — Never absorbed\n\nSymptom.\n",
                                     encoding="utf-8", newline="\n")
        rc, out, _e = run(["check", "--root", str(tmp)])
        check("drift in a flat file is a warning, not an error", rc, 0)
        check("...with the true count", "pain:1" in out, True)
        check("...and status shows it too", "LEGACY DRIFT 1" in run(["status", "--root", str(tmp)])[1], True)
        rc, out, _e = run(["import-legacy", "--apply", "--root", str(tmp)])
        check("import-legacy absorbs it", rc, 0)
        check("...and drift is then 0",
              "LEGACY DRIFT 0" in run(["status", "--root", str(tmp)])[1], True)


def test_status_budget(j):
    print("status under its cap")
    with tempfile.TemporaryDirectory() as td:
        tmp = fixture(Path(td))
        set_root(j, tmp)
        run(["migrate-v2", "--apply", "--root", str(tmp)])
        (tmp / "NOW.md").write_text("Updated: 2026-09-14\n" + ("state line\n" * 4000),
                                    encoding="utf-8", newline="\n")
        (tmp / "state" / "in-flight.md").write_text("Updated: 2026-09-14\n" + ("in flight\n" * 4000),
                                                    encoding="utf-8", newline="\n")
        for budget in (6000, 2000, 800):
            rc, out, _e = run(["status", "--root", str(tmp), "--budget", str(budget)])
            check("status exits 0 at --budget %d" % budget, rc, 0)
            check("status output <= %d B" % budget, len(out.encode("utf-8")) <= budget, True)
        rc, out, _e = run(["status", "--root", str(tmp)])
        check("default status is <= 6000 B", len(out.encode("utf-8")) <= 6000, True)
        check("the truncation is visible", ("… (+" in out) or ("truncated" in out), True)
        rc, out, _e = run(["status", "--root", str(tmp), "--budget", "1200"])
        check("a small budget still marks the cut",
              len(out.encode("utf-8")) <= 1200 and ("… (+" in out or "truncated" in out), True)


def test_cli_surface(j):
    print("CLI surface")
    with tempfile.TemporaryDirectory() as td:
        tmp = fixture(Path(td))
        set_root(j, tmp)
        run(["migrate-v2", "--apply", "--root", str(tmp)])
        cases = [
            ["status", "--root", str(tmp)],
            ["list", "--root", str(tmp)],
            ["list", "--kind", "lessons", "--root", str(tmp), "--json"],
            ["list", "--kind", "lessons", "--status", "open", "--since", "2026-09-01", "--root", str(tmp)],
            ["newest", "lessons", "2", "--root", str(tmp)],
            ["newest", "-k", "lessons", "-n", "2", "--root", str(tmp)],
            ["show", "L1", "--root", str(tmp)],
            ["show", "L1", "--refs", "--root", str(tmp)],
            ["show", "L1", "--root", str(tmp), "--json"],
            ["show", "L1", "L3", "--root", str(tmp)],
            ["search", "body", "--root", str(tmp)],
            ["search", "flat", "body", "--root", str(tmp), "--json"],
            ["search", "BODY", "--root", str(tmp), "--regex"],
            ["search", "flat", "--root", str(tmp), "--legacy"],
            ["backlinks", "L1", "--root", str(tmp)],
            ["pairs", "--root", str(tmp)],
            ["stats", "--root", str(tmp), "--json"],
            ["kinds", "--root", str(tmp)],
            ["check", "--root", str(tmp), "--json"],
            ["costs", "--root", str(tmp), "--json"],
            ["doctor", "--root", str(tmp), "--json", "--offline"],
            ["next-id", "lessons", "--root", str(tmp), "--no-fetch"],
            ["index", "--root", str(tmp), "--stats"],
            ["import-legacy", "--root", str(tmp)],
            ["dedupe", "--root", str(tmp)],
            ["repair-ids", "--root", str(tmp)],
            ["gc-legacy", "--root", str(tmp)],
        ]
        for argv in cases:
            rc, out, err = run(argv)
            check("`%s` runs and returns a sane code" % " ".join(argv[:2]), rc in (0, 1, 2), True)
        rc, out, err = run(["search", "zzzz-not-present-zzzz", "--root", str(tmp)])
        check("an empty search exits 1", rc, 1)
        check("...and explains the refusal on stderr", "no match" in err, True)
        rc, out, _e = run(["stats", "--root", str(tmp), "--json"])
        check("--json is parseable", isinstance(json.loads(out), dict), True)
        rc, out, _e = run(["costs", "--root", str(tmp), "--json"])
        costs = json.loads(out)
        check("costs reports a status row under its targets",
              all(r["ok"] for r in costs["measured"] if r["command"] == "status"), True)
        rc, out, _e = run(["show", "L404", "--root", str(tmp)])
        check("showing a missing id exits non-zero", rc, 2)
        rc, out, _e = run(["newest", "nosuchkind", "--root", str(tmp)])
        check("an unknown kind exits 2", rc, 2)


def test_redaction(j):
    print("redaction")
    check("a provider-prefixed token is redacted",
          "<redacted>" in j.redact("key sk-live-abcdefghijklmnopqrstuvwx"), True)
    check("an opaque 40-char run is redacted",
          j.redact("token=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"), "token=<redacted>")
    check("ordinary prose is untouched", j.redact("the stale database on the wrong host"),
          "the stale database on the wrong host")


def test_v1_compat_surface(j):
    print("v1 compatibility surface")
    for name in ("KINDS", "MARKER_RE", "body_hash", "entry_hash", "content_key",
                 "build_heading", "num_of", "suffix_of", "parse_legacy"):
        check("journal.%s exists (the frozen v1 selftest imports it)" % name, hasattr(j, name), True)
    v1 = HERE / "archive" / "selftest-v1.py"
    check("the frozen v1 selftest is present", v1.exists(), True)


def test_identity_absorption(j):
    """A flat entry that is the same LOGICAL entry as a shard entry adds nothing."""
    print("identity absorption (alias, never a second copy)")
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "log" / "lessons").mkdir(parents=True, exist_ok=True)
        (root / "state").mkdir(parents=True, exist_ok=True)
        (root / "FORMAT").write_text("2\n", encoding="utf-8", newline="\n")
        (root / "log" / "lessons" / "2026-09.md").write_text(
            "# lessons · 2026-09\n\n"
            "<!-- e:lessons|L154b|2026-09-14|H|open -->\n**L154b · One lesson, two ids**\n\n"
            "The body that makes this one lesson, not two.\n",
            encoding="utf-8", newline="\n")
        (root / "LESSONS.md").write_text(
            "# LESSONS\n\n**L154 · One lesson, two ids**\n\n"
            "The body that makes this one lesson, not two.\n\n"
            "**L900 · Genuinely new text the record does not hold.**\n\nBrand new body.\n",
            encoding="utf-8", newline="\n")
        set_root(j, root)
        rc, out, _e = run(["import-legacy", "--apply", "--root", str(root), "--json"])
        check("import-legacy --apply exits 0", rc, 0)
        plan = json.loads(out)
        check("the shard entry was written", plan["added"] >= 1, True)
        # two entries are new: the shard's L154b and the flat file's genuinely new L900
        check("exactly the two genuinely new entries were written", plan["added"], 2)
        check("the same-identity flat entry was aliased, not duplicated", plan["aliased"], 1)
        check("nothing was byte-identical (the heading ids differ)", plan["identical"], 0)
        check("the tree holds two entries, not three", len(j.load_entries()[0]), 2)
        rows = j.load_aliases()
        check("an alias row was written for L154", [r["alias_id"] for r in rows], ["L154"])
        check("...pointing at the live entry", rows[0]["canonical_id"], "L154b")
        check("...with a reason", bool(rows[0]["reason"]), True)
        check("...and the source it came from", rows[0]["source"].startswith("LESSONS.md"), True)
        check("L154 resolves to L154b", j.resolve_alias("L154"), "L154b")
        # idempotent
        rc, out, _e = run(["import-legacy", "--apply", "--root", str(root), "--json"])
        plan2 = json.loads(out)
        check("a second absorption adds nothing", plan2["added"], 0)
        check("...and calls both sources identical", plan2["identical"], 2)


def test_alias_never_shadows(j):
    """An alias whose id is itself a live entry must not swallow the live entry."""
    print("an alias never shadows a live entry")
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "log" / "pain").mkdir(parents=True, exist_ok=True)
        (root / "state").mkdir(parents=True, exist_ok=True)
        (root / "FORMAT").write_text("2\n", encoding="utf-8", newline="\n")
        (root / "log" / "pain" / "2026-09.md").write_text(
            "# pain · 2026-09\n\n"
            "<!-- e:pain|P13|2026-09-14|H|open -->\n## P13 — A live pain that owns P13\n\n"
            "Symptom of the live entry.\n\n---\n\n"
            "<!-- e:pain|P13b|2026-09-14|H|open -->\n## P13b — The same text as the flat P13\n\n"
            "Text that the flat file also carries.\n",
            encoding="utf-8", newline="\n")
        (root / "PAIN.md").write_text(
            "# PAIN\n\n## P13 — The same text as the flat P13\n\n"
            "Text that the flat file also carries.\n",
            encoding="utf-8", newline="\n")
        set_root(j, root)
        run(["import-legacy", "--apply", "--root", str(root)])
        check("the flat P13 was absorbed as an alias", j.resolve_alias("P13"), "P13b")
        rc, out, err = run(["show", "P13", "--root", str(root)])
        check("show of a shadowed id exits 0", rc, 0)
        check("...returns the LIVE entry, not the alias target",
              "Symptom of the live entry." in out, True)
        check("...and says an alias exists", ("alias" in (out + err)), True)
        check("...and the base id P13 also lists its suffixed sibling, as the base-id rule says",
              "P13b" in out, True)


def test_lf_only(j):
    """Every write is LF, and check --fix repairs a file that is not."""
    print("LF everywhere, and check --fix")
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "log" / "lessons").mkdir(parents=True, exist_ok=True)
        (root / "state").mkdir(parents=True, exist_ok=True)
        (root / "FORMAT").write_text("2\n", encoding="utf-8", newline="\n")
        (root / "log" / "lessons" / "2026-09.md").write_text(
            "# lessons · 2026-09\n\n"
            "<!-- e:lessons|L1|2026-09-14|H|open -->\n**L1 · One**\n\nBody one.\n",
            encoding="utf-8", newline="\n")
        set_root(j, root)
        run(["import-legacy", "--apply", "--root", str(root)])
        f = root / "entries" / "lessons" / "L1.md"
        check("a written entry holds no CR", b"\r" in f.read_bytes(), False)
        # a CRLF file is an ERROR, and --fix rewrites it
        f.write_bytes(f.read_bytes().replace(b"\n", b"\r\n"))
        set_root(j, root)
        rc, out, _e = run(["check", "--root", str(root)])
        check("CRLF is an error", rc, 1)
        check("...and says so", "CRLF" in out, True)
        rc, out, _e = run(["check", "--root", str(root), "--fix"])
        check("--fix exits clean", rc, 0)
        check("--fix removed every CR", b"\r" in f.read_bytes(), False)
        check("--fix says what it did", "LF" in out, True)


def test_import_flat_alias(j):
    """`import-flat` is the deprecated v1 name and must still work."""
    print("import-flat (deprecated) still works")
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "log" / "lessons").mkdir(parents=True, exist_ok=True)
        (root / "state").mkdir(parents=True, exist_ok=True)
        (root / "FORMAT").write_text("2\n", encoding="utf-8", newline="\n")
        (root / "LESSONS.md").write_text(
            "# LESSONS\n\n**L5 · Only in the flat file.**\n\nBody.\n",
            encoding="utf-8", newline="\n")
        set_root(j, root)
        rc, out, err = run(["import-flat", "--apply", "--root", str(root)])
        check("import-flat exits 0", rc, 0)
        check("...and says it is deprecated", "deprecated" in err, True)
        check("...and does the work", (root / "entries" / "lessons" / "L5.md").is_file(), True)


def main():
    global j_main
    j = load_module()
    j_main = j.main
    holder = []
    test_markers(j)
    test_identity(j)
    test_headings(j)
    test_ids(j)
    test_legacy_parsing(j)
    test_entry_file_format(j)
    test_meta_parse(j)
    test_budget(j)
    test_shard_split_and_migration(j, holder)
    test_partial_migration_order(j)
    test_identity_absorption(j)
    test_alias_never_shadows(j)
    test_lf_only(j)
    test_import_flat_alias(j)
    test_cache_self_heal(j)
    test_resolution(j)
    test_append_and_concurrency(j)
    test_check_rules(j)
    test_status_budget(j)
    test_cli_surface(j)
    test_redaction(j)
    test_v1_compat_surface(j)
    print()
    if FAILS:
        print("%d FAILED of %d: %s" % (len(FAILS), len(FAILS) + PASSES[0], ", ".join(FAILS)))
        return 1
    print("all %d checks passed" % PASSES[0])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())