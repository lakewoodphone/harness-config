#!/usr/bin/env python3
"""test_journal_search.py — `search` must match entry BODIES, not only headings.

    python -m pytest journal/tools/test_journal_search.py

Why this file exists. `catalog()` answers from `index/entries.tsv`, and `_from_tsv()`
built every Entry with `body=""`, so `search` could only ever match a heading. Entry
W136's body contains "inter-start gap" and `search "inter-start gap"` answered
`no match` — which reads as *never recorded*. That is the most expensive thing this
memory system can say wrongly, so the fix is covered here rather than trusted.

CONVENTION, stated plainly because it did not exist before: harness-config had no
`tests/` directory when this was written (2026-09-15). `journal/tools/selftest.py` was
the only harness — a hand-rolled `check()` runner over the format, the cache and the
budgeter, with no pytest and no path-level regression tests for this read path. This
file introduces pytest as the convention for a single-command regression, and follows
selftest.py's mechanics exactly: it loads `journal.py` by path (`load_module`), runs
commands in-process through `main()` (`run`), pins the root with `clear_caches()`
(`set_root`), and only ever touches a pytest temp directory — never the live journal.

The suite is built so a fix that simply matches everything cannot pass: the primary
probe term appears in no heading and in exactly two known bodies, and there are three
negative controls (a phrase present nowhere, a superstring of a real term, and two
patterns that never share a line).
"""
from __future__ import annotations

import importlib.util
import io
import json
import os
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent

# A term that no heading carries and exactly two fixture bodies do.
BODY_TERM = "sentinel-drift-gauge"
# A phrase that appears nowhere in the fixture tree, or in the journal.
NOWHERE_TERM = "zzq-nowhere-phrase-4417"

# ---------------------------------------------------------------------------
# Mechanics, copied from selftest.py so there is one way to drive this tool
# ---------------------------------------------------------------------------


def load_module():
    """Import journal.py by path, so a fixture root can be attached to it."""
    spec = importlib.util.spec_from_file_location("journal_under_test_%d" % os.getpid(),
                                                  str(HERE / "journal.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run(mod, argv):
    """Run a journal command in-process, capturing stdout/stderr. Returns (rc, out, err)."""
    buf, err = io.StringIO(), io.StringIO()
    with redirect_stdout(buf), redirect_stderr(err):
        rc = mod.main(argv)
    return rc, buf.getvalue(), err.getvalue()


def set_root(mod, root: Path) -> None:
    """Point the module at a fixture root exactly as --root does, caches included."""
    mod.JOURNAL = Path(root)
    mod.clear_caches()


def add(mod, kind, title, body, date="2026-09-15"):
    """One entry through the only sanctioned writer. Returns its id."""
    rc, out, err = run(mod, ["append", kind, "--title", title, "--body", body,
                             "--date", date, "--host", "TEST", "--no-fetch"])
    assert rc == 0, "append failed: rc=%s out=%r err=%r" % (rc, out, err)
    for e in mod.load_entries()[0]:
        if title in e["heading"]:
            return e["id_full"]
    raise AssertionError("appended entry not findable by title: %r" % title)


def bare_root(root: Path) -> Path:
    (root / "index").mkdir(parents=True, exist_ok=True)
    (root / "log" / "lessons").mkdir(parents=True, exist_ok=True)
    (root / "FORMAT").write_text("2\n", encoding="utf-8", newline="\n")
    return root


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def build_tree(root: Path):
    """A temp journal root whose only interesting text is INSIDE bodies."""
    bare_root(root)
    mod = load_module()
    set_root(mod, root)
    ids = {
        "body_lesson": add(mod, "lessons", "A title that never names the instrument",
                           "The %s reported 12 units at 03:00." % BODY_TERM),
        "body_win": add(mod, "wins", "A win with an unremarkable title",
                        "Second body holding %s as well." % BODY_TERM),
        "two_lines": add(mod, "lessons", "The instrument shows up twice in this body",
                         "line one mentions %s.\nline two mentions %s again." % (BODY_TERM, BODY_TERM)),
        "split_lines": add(mod, "lessons", "Two markers kept apart on purpose",
                           "alpha-token sits on this line.\nbeta-token sits on that one."),
        "same_line": add(mod, "lessons", "Two markers kept together on purpose",
                         "alpha-token and beta-token share one line here."),
        "heading_only": add(mod, "lessons", "marmalade-orbit appears in the heading",
                            "Nothing distinctive in this body."),
    }
    return mod, root, ids


@pytest.fixture(scope="module")
def tree(tmp_path_factory):
    """One tree for the read-only tests: building it is six cache rebuilds, so share it."""
    return build_tree(tmp_path_factory.mktemp("journal-tree") / "journal")


@pytest.fixture()
def own_tree(tmp_path):
    """A private tree, for the tests that mutate their root (cache, db or entries)."""
    return build_tree(tmp_path / "journal")


@pytest.fixture()
def legacy_tree(tmp_path):
    """A root whose term lives only in a frozen v1 shard, for --legacy."""
    root = bare_root(tmp_path / "journal")
    # A hand-written shard makes the cache permanently stale (log_sig moves), so this
    # fixture is kept away from the cache-tier tests below.
    (root / "log" / "lessons" / "2026-09.md").write_text(
        "# lessons · 2026-09\n"
        "<!-- journal shard: append-only -->\n\n"
        "<!-- e:lessons|L1|2026-09-14|ZABZ-YOGA|open -->\n"
        "**L1 · A legacy rule with a plain heading**\n\n"
        "Only the shard body carries %s.\n" % BODY_TERM,
        encoding="utf-8", newline="\n")
    mod = load_module()
    set_root(mod, root)
    return mod, root


# ---------------------------------------------------------------------------
# The defect
# ---------------------------------------------------------------------------


def test_the_probe_term_is_body_only(tree):
    """Guard the guard: if the term were in a heading, every test below would lie."""
    mod, _root, _ids = tree
    entries, _problems = mod.load_entries()
    assert entries
    for e in entries:
        assert BODY_TERM not in e["heading"], "fixture is not body-only: %s" % e["id_full"]
        assert BODY_TERM not in e["file"]


def test_a_body_only_term_is_found(tree):
    """THE REGRESSION. Fails on the unfixed tool with rc=1 / 'no match'."""
    mod, _root, ids = tree
    rc, out, err = run(mod, ["search", BODY_TERM])
    assert rc == 0, "search found nothing in a body; stderr=%r" % err
    assert ids["body_lesson"] in out
    assert ids["body_win"] in out
    assert ids["two_lines"] in out


def test_body_matches_report_the_body_line_not_the_heading(tree):
    """A snippet must come from the body, so the caller can see the evidence."""
    mod, _root, _ids = tree
    _rc, out, _err = run(mod, ["search", BODY_TERM, "--json"])
    hits = {h["id"]: h for h in json.loads(out)["hits"]}
    assert hits
    for h in hits.values():
        first = h["lines"][0]["text"]
        assert BODY_TERM in first.lower(), first
        assert BODY_TERM not in h["heading"].lower()


def test_body_search_survives_a_missing_journal_db(own_tree):
    """Tier 3: index/journal.db is gitignored, so a fresh clone has no bodies in cache."""
    mod, root, ids = own_tree
    db = root / "index" / "journal.db"
    assert db.exists(), "the fixture should have built a db cache"
    with_db = run(mod, ["search", BODY_TERM])
    db.unlink()
    rc, out, err = run(mod, ["search", BODY_TERM])
    assert rc == 0, err
    assert ids["body_lesson"] in out and ids["body_win"] in out
    # Both tiers must produce byte-identical output, or the cache changes the answer.
    assert out == with_db[1]
    assert not db.exists(), "tier 3 read; it must not silently rebuild the db"


def test_body_search_survives_an_empty_cache(own_tree):
    """The fresh-clone path: no db, no stamp, no tsv — the cache rebuilds, search works."""
    mod, root, ids = own_tree
    for name in ("journal.db", "stamp.json", "entries.tsv"):
        (root / "index" / name).unlink()
    rc, out, err = run(mod, ["search", BODY_TERM])
    assert rc == 0, err
    assert ids["body_lesson"] in out and ids["body_win"] in out


# ---------------------------------------------------------------------------
# Negative controls: a fix that matches everything must not pass
# ---------------------------------------------------------------------------


def test_negative_control_phrase_still_reports_no_match(tree):
    mod, _root, _ids = tree
    # Make the control real: prove the phrase is absent from the tree, not just unfound.
    for e in mod.load_entries()[0]:
        assert NOWHERE_TERM not in e["heading"]
        assert NOWHERE_TERM not in e["body"]
    rc, out, err = run(mod, ["search", NOWHERE_TERM])
    assert rc == 1
    assert "no match" in err
    assert out.strip() == ""


def test_a_superstring_of_a_real_body_term_is_not_a_match(tree):
    """Guards against a fix that widens matching until everything matches."""
    mod, _root, _ids = tree
    rc, out, _err = run(mod, ["search", BODY_TERM + "-extended"])
    assert rc == 1, out
    rc, out, _err = run(mod, ["search", "sentinel-drift-gauged"])
    assert rc == 1, out
    rc, out, _err = run(mod, ["search", "sentineldriftgauge"])
    assert rc == 1, out


def test_plain_mode_is_still_a_substring_match(tree):
    """Documents the semantics deliberately, so nobody 'fixes' it into word matching.

    The old code did `p.lower() in ln.lower()` on the heading. Bodies are now matched
    the same way: a substring of a real term matches, which is why `drift-gauge` finds
    the three fixture bodies. Changing that would be a different defect.
    """
    mod, _root, ids = tree
    rc, out, _err = run(mod, ["search", "drift-gauge"])
    assert rc == 0
    assert ids["body_lesson"] in out and ids["body_win"] in out


def test_all_patterns_must_share_a_line(tree):
    """Plain mode: every pattern on the SAME line — preserved from the old behaviour."""
    mod, _root, ids = tree
    rc, out, err = run(mod, ["search", "alpha-token", "beta-token"])
    assert rc == 0, err
    assert ids["same_line"] in out
    assert ids["split_lines"] not in out


# ---------------------------------------------------------------------------
# Existing behaviour, kept exactly
# ---------------------------------------------------------------------------


def test_heading_matches_still_work(tree):
    mod, _root, ids = tree
    rc, out, err = run(mod, ["search", "marmalade-orbit"])
    assert rc == 0, err
    assert ids["heading_only"] in out


def test_matching_is_case_insensitive(tree):
    mod, _root, ids = tree
    rc, out, _err = run(mod, ["search", BODY_TERM.upper()])
    assert rc == 0
    assert ids["body_lesson"] in out


def test_regex_mode_matches_a_body(tree):
    mod, _root, ids = tree
    rc, out, _err = run(mod, ["search", "sentinel-drift-gau.e", "--regex"])
    assert rc == 0
    assert ids["body_lesson"] in out


def test_kind_filter_still_restricts_a_body_search(tree):
    mod, _root, ids = tree
    rc, out, err = run(mod, ["search", BODY_TERM, "--kind", "wins"])
    assert rc == 0, err
    assert ids["body_win"] in out
    assert ids["body_lesson"] not in out


def test_since_and_until_still_bound_a_body_search(own_tree):
    mod, _root, ids = own_tree
    old = add(mod, "lessons", "An old entry that still holds the instrument",
              "Ancient body holding %s." % BODY_TERM, date="2020-01-01")
    rc, out, _err = run(mod, ["search", BODY_TERM, "--since", "2026-01-01"])
    assert rc == 0
    assert old not in out and ids["body_lesson"] in out
    rc, out, _err = run(mod, ["search", BODY_TERM, "--until", "2021-01-01"])
    assert rc == 0
    assert old in out and ids["body_lesson"] not in out


def test_context_still_widens_the_snippet(tree):
    mod, _root, ids = tree
    _rc, out, _err = run(mod, ["search", BODY_TERM, "--json"])
    one = [h for h in json.loads(out)["hits"] if h["id"] == ids["two_lines"]][0]
    _rc, out_ctx, _err = run(mod, ["search", BODY_TERM, "--json", "--context", "1"])
    two = [h for h in json.loads(out_ctx)["hits"] if h["id"] == ids["two_lines"]][0]
    assert len(one["lines"]) == 1
    assert len(two["lines"]) == 2


def test_json_shape_and_limit_are_unchanged(tree):
    mod, _root, _ids = tree
    rc, out, _err = run(mod, ["search", BODY_TERM, "--json"])
    assert rc == 0
    payload = json.loads(out)
    assert set(payload) >= {"root", "source", "total_matches", "hits"}
    assert payload["total_matches"] >= 3
    for h in payload["hits"]:
        assert set(h) >= {"id", "kind", "heading", "file", "lines"}
        for ln in h["lines"]:
            assert set(ln) == {"line", "text"}
    rc, out, _err = run(mod, ["search", BODY_TERM, "--json", "--limit", "1"])
    assert rc == 0
    assert len(json.loads(out)["hits"]) == 1


def test_budget_still_caps_the_page_and_says_so(tree):
    mod, _root, _ids = tree
    rc, out, _err = run(mod, ["search", BODY_TERM, "--budget", "300"])
    assert rc == 0
    assert len(out.encode("utf-8")) <= 300
    assert "(+" in out, "a capped page must say it was capped: %r" % out


def test_legacy_search_still_reads_shard_bodies(legacy_tree):
    mod, _root = legacy_tree
    rc, out, err = run(mod, ["search", BODY_TERM, "--legacy"])
    assert rc == 0, err
    assert "L1" in out


def test_no_pattern_is_still_a_usage_error(tree):
    """`pattern` is a required positional, so argparse exits 2 before any read."""
    mod, _root, _ids = tree
    with pytest.raises(SystemExit) as exc:
        run(mod, ["search"])
    assert exc.value.code == 2
