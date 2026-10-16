#!/usr/bin/env python3
"""roadmap-supply - the source that turns a project's own roadmap into ledger work.

THE GAP THIS CLOSES (measured 2026-10-07, ledger item 501)
  `project-keepalive` wakes a project when `/home/zabz/.wake-projects/<id>.json` says
  `work_remaining`, and `ledger-keepalive` wakes it when the ledger holds a `todo` item. Both
  read the world correctly and both can therefore go permanently quiet: nothing in the loop
  reads the ROADMAP. For kosher-ai-filter that produced a two-state oscillation, both states
  measured. Either the ledger held no `todo` item at all (0 todo / 5 blocked, 2026-10-07 04:20Z)
  and no shift was woken, or the only open item was a duplicate `Integrate <branch>` refile
  (items 488/494/498/500, three duplicate branches at one commit, item 500 deliberately kept
  `blocked` as the dedupe guard because a `dropped` row lets the generator refile the same title
  every hour). Meanwhile the project's own docs carry dozens of unchecked boxes with real
  definitions of done - a web password reset, a readiness endpoint, a watchdog service, an
  Android provisioning path - none of which any generator had ever read.

WHAT IT DOES
  Reads a per-project mapping file (`roadmap-<project>.json`, authored deliberately, never
  inferred) and, for each unchecked checkbox in the docs it names, files ONE ledger item when
  that item does not already exist in a live state. It also reports the reverse direction: a
  checkbox in the named docs with no mapping row, which is how a new roadmap entry gets noticed
  instead of silently ignored. Both directions are on stdout, so the daily log shows the state
  of the supply, not just that the source ran.

WHAT IT NEVER DOES
  * Never invents work. Every filed item traces to a checkbox string in a named doc, and every
    item carries a `dod` that names the command and the result that counts as done. A mapping
    row with `status: not_filed` is a deliberate refusal, with the reason in `why`.
  * Never refiles. Dedup is by exact title against the ledger's own live states
    (`todo`, `running`, `blocked`), so a blocked guard row (like item 500) does what it was kept
    for. It does not keep its own state file: the ledger is the only state.
  * Never files a project's worth of work in one run. `--limit` (default 3 new items per run)
    exists because a source that files fifty rows is a backlog nobody reads; the source runs on
    every sources pass, so the rest arrive over the following runs.
  * Never reports health from an unreadable signal. A missing doc, an unreadable ledger or a
    malformed mapping file prints the reason on stderr and exits non-zero - never the word
    `quiet`. A problem with no open items prints `quiet` (nothing to file) and the counts on
    stderr.

USAGE
  python3 roadmap-supply.py --project kosher-ai-filter            # live
  python3 roadmap-supply.py --project kosher-ai-filter --dry-run  # decide, write nothing
  python3 roadmap-supply.py --check-projects                      # which projects have a mapping
  python3 roadmap-supply.py --selfcheck                           # pure-logic assertions, no store

Exit: 0 on a completed run (including "nothing to do"), 1 when a signal could not be read.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORK_CLI = os.environ.get("WORK_CLI") or str(Path.home() / "bin" / "work.py")
WORK_DB = os.environ.get("WORK_DB") or str(Path.home() / "work" / "work.db")
REGISTRY = Path(os.environ.get("WORK_REGISTRY") or (HERE / "projects.json"))
SOURCE = "roadmap-supply"
KEY_CHARS = 60
LIVE_STATES = ("todo", "running", "blocked")

# A checkbox at the start of a line (optionally indented): "- [ ]", "* [ ]", "+ [ ]".
BOX_RE = re.compile(r"^\s*[-*+]\s*\[( |x|X)\]\s*(.*)$")

# The definition of done attached to the renewal item. It is deliberately mechanical: an author
# of a definition of done cannot be allowed to write prose and call it work, so the item demands
# that the source's own validator and selfcheck pass and that the counts move in a stated
# direction, all of which another agent can re-run without trusting the author.
AUTHORING_DOD = (
    "Extend the mapping file {manifest} with "
    "a row for EVERY unchecked box this item names, and prove it mechanically - not by assertion. "
    "DONE requires, quoted: (1) `python3 {source} --project {project} --selfcheck` -> 0 failed. "
    "(2) `python3 {source} --project {project} --dry-run` with the BEFORE counts quoted "
    "(unmapped_boxes=N) and the AFTER counts quoted "
    "(unmapped_boxes=M), where M <= N - new_rows; a row whose `key` does not resolve to a real "
    "checkbox will show up as STALE-MAPPING and that proves the row wrong, so a run with a "
    "STALE-MAPPING line is a FAILED attempt, not a partial one. (3) the real run "
    "(no --dry-run) showing filed_this_run > 0 for the newly mapped boxes, or 0 with the reason "
    "quoted if every new row was already live. (4) every new row carries: a `dod` naming the exact "
    "command to run AND the result line that counts as done; a `host` whose abilities the mapping "
    "file's `capability_matrix` actually claims - READ IT FIRST, because a dod on a host that cannot "
    "run it is an item that will stall (measured 2026-10-07: mac-mini-ts compiles Apple code but has "
    "no XCTest, Yoga's Windows Swift cannot build the iOS package at all, the authority has no "
    "java/dotnet/swift, and the desktop cannot ssh); and a status of either `filed` or `not_filed` - a "
    "`not_filed` row MUST carry the reason (a spend, a hardware requirement, an owner decision, or "
    "a recorded deferral) in its `why`. (5) `git diff --stat` of the harness repo and the pushed "
    "branch name. FORBIDDEN: a row whose dod is unprovable ('improve X', 'research Y'), a row "
    "filed to keep the loop alive, and marking this item done while any box it names is still "
    "without a row."
)


def norm_key(text: str) -> str:
    """The match key for a checkbox line: lowercase, markers stripped, punctuation unified.

    Only a PREFIX is compared (KEY_CHARS). Measured reason: these docs append evidence inside
    the same checkbox line ("(ledger item 15, done 2026-09-29; branch ... => 29 passed)"), so a
    full-line key would break the moment a shift records its own proof - the mapping would
    silently stop matching and the source would refile the item it had already filed.

    Punctuation is unfolded because the docs use typographic characters (em dash U+2014, curly
    quotes, the section sign) while a mapping file typed on another keyboard uses the ASCII
    forms. Measured 2026-10-07: a key authored as "watchdog service - second service ..." did
    not match a checkbox written "watchdog service — second service ...", and the box was
    reported as unmapped while the mapping row looked present - a silent both-directions miss.
    """
    s = (text or "").strip()
    for a, b in (("\u2014", "-"), ("\u2013", "-"), ("\u2018", "'"), ("\u2019", "'"),
                 ("\u201c", '"'), ("\u201d", '"'), ("\u00a7", "s"), ("\u2264", "<="),
                 ("\u00a0", " ")):
        s = s.replace(a, b)
    s = s.replace("**", "").replace("`", "")
    s = re.sub(r"^[-*+\s]+", "", s)
    s = re.sub(r"^\[[ xX]\]\s*", "", s)  # a checkbox marker typed into the key itself
    s = " ".join(s.split()).lower()
    # The key is stripped AFTER truncation as well as before. Measured 2026-10-07: when the
    # first 60 characters of a doc line end in a space, the doc key and the manifest key (typed
    # from the same words, already stripped) differed by exactly that trailing space, and three
    # perfectly good mapping rows were reported as STALE on every run. A validator that cries
    # wolf on its own keys is worse than none, because the real stale row (a deleted checkbox)
    # then hides in the noise.
    return s[:KEY_CHARS].strip()


def parse_boxes(path: Path) -> list[dict]:
    """Every checkbox in one doc, with its 1-based line number, key and checked flag."""
    out: list[dict] = []
    for i, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        m = BOX_RE.match(line)
        if not m:
            continue
        out.append({"line": i, "checked": m.group(1).lower() == "x",
                    "text": m.group(2).strip(), "key": norm_key(m.group(2))})
    return out


def ledger_live(db: Path, project: str) -> dict:
    """{exact title: (id, state)} for every item of this project in a live state."""
    if not db.exists():
        raise FileNotFoundError("ledger not found: %s" % db)
    c = sqlite3.connect("file:%s?mode=ro" % db, uri=True, timeout=20.0)
    c.row_factory = sqlite3.Row
    try:
        rows = c.execute(
            "SELECT id, title, state FROM work_item WHERE project=? AND state IN (%s)"
            % ",".join("?" * len(LIVE_STATES)), (project, *LIVE_STATES)).fetchall()
        return {r["title"]: (r["id"], r["state"]) for r in rows}
    finally:
        c.close()


def ledger_counts(db: Path, project: str) -> dict:
    c = sqlite3.connect("file:%s?mode=ro" % db, uri=True, timeout=20.0)
    try:
        rows = c.execute("SELECT state, COUNT(*) FROM work_item WHERE project=? GROUP BY state",
                         (project,)).fetchall()
        return {r[0]: r[1] for r in rows}
    finally:
        c.close()


def work_add(project: str, item: dict, dry_run: bool) -> tuple[bool, str]:
    """File one item through the ledger CLI, so every rule the CLI enforces still applies."""
    cmd = ["python3", WORK_CLI, "add", "--project", project, "--title", item["title"],
           "--dod", item["dod"], "--why", item.get("why", ""),
           "--priority", str(item.get("priority", 5)), "--source", SOURCE]
    if dry_run:
        return True, "DRY-RUN would file: %s" % item["title"]
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=120)
    out = " ".join(((p.stdout or "") + (p.stderr or "")).split())
    return p.returncode == 0, out[:200]


def load_mapping(path: Path) -> dict:
    d = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(d, dict) or not isinstance(d.get("items"), list):
        raise ValueError("mapping file has no items list: %s" % path)
    return d


def compute_uncovered(unchecked: list, by_key: dict, live: dict) -> list:
    """Boxes that would go nowhere once the current queue drains.

    Ledger item 421, measured 2026-10-16: this used to be "any checked-unchecked box whose
    mapping row is not status=filed", which counted the project's 13 `not_filed` rows as
    uncovered forever. Those rows are deliberate, recorded refusals - an iOS hardware gate, a
    WHQL signature, the Q22 PIR deferral, a model spend - and each carries its reason in `why`,
    which the authoring item's own definition of done permits. Counting them kept the renewal
    item open forever, so every cycle refiled an authoring item whose dod was already satisfied
    and spent a shift re-reading the same 13 rows. A gap is now only:

      * a box with NO mapping row at all;
      * a `filed` row whose title is not live in the ledger (the row claims an item that is not
        there, so the box really would go nowhere); or
      * a `not_filed` row with an EMPTY `why` (an unexplained refusal is not an authored row).

    A `not_filed` row that carries its reason is authored work: it is not a box without a
    definition of done, it is a box whose definition of done is "do not file this, and here is
    why". Pure function, no store - so the selfcheck can assert it.
    """
    out = []
    for b in unchecked:
        it = by_key.get(b["key"])
        if it is None:
            out.append(b)
            continue
        status = it.get("status")
        if status == "filed":
            if it.get("title") not in live:
                out.append(b)
        elif status == "not_filed":
            if not str(it.get("why") or "").strip():
                out.append(b)
        else:
            out.append(b)
    return out


def run(args) -> int:
    mapping_path = HERE / ("roadmap-%s.json" % args.project)
    if not mapping_path.exists():
        print("no mapping file for project %s (%s)" % (args.project, mapping_path), file=sys.stderr)
        return 1
    mapping = load_mapping(mapping_path)

    registry = {}
    try:
        reg = json.loads(REGISTRY.read_text(encoding="utf-8"))
        registry = {p["id"]: p for p in reg.get("projects", [])}
    except Exception as exc:  # the registry is not this source's subject; a mapping file may name a repo directly
        print("warning: could not read %s (%s)" % (REGISTRY, exc), file=sys.stderr)
    proj = registry.get(args.project) or {}
    repo = Path(args.repo or proj.get("repo") or "")
    if not repo or not repo.exists():
        print("cannot read the project repo for %s: %r" % (args.project, str(repo)), file=sys.stderr)
        return 1

    # 1. document direction: unchecked boxes, checked boxes, and the mapping match.
    doc_keys: dict[str, set] = {}
    unchecked: list[dict] = []
    for rel in mapping.get("source_docs", []):
        p = repo / rel
        if not p.exists():
            print("source doc missing: %s" % p, file=sys.stderr)
            return 1
        boxes = parse_boxes(p)
        doc_keys[rel] = {b["key"] for b in boxes}
        for b in boxes:
            if not b["checked"]:
                unchecked.append({**b, "src": rel})

    by_key: dict[str, dict] = {}
    for it in mapping["items"]:
        k = norm_key(it["key"])
        if k in by_key:
            print("mapping file lists the same key twice: %r" % it["key"], file=sys.stderr)
            return 1
        by_key[k] = it

    matched: set[str] = set()
    to_file: list[dict] = []
    for box in unchecked:
        it = by_key.get(box["key"])
        if it is None:
            continue
        matched.add(box["key"])
        if it.get("status") != "filed":
            continue
        to_file.append({**it, "src": box["src"], "line": box["line"]})

    # A mapped box that is now CHECKED in the doc is done by the docs' own record; nothing to file.
    checked_keys = set()
    for rel in mapping.get("source_docs", []):
        for b in parse_boxes(repo / rel):
            if b["checked"]:
                checked_keys.add(b["key"])
    to_file = [i for i in to_file if norm_key(i["key"]) not in checked_keys]

    # 2. ledger direction: what already exists, and what is new.
    try:
        live = ledger_live(Path(WORK_DB), args.project)
        counts = ledger_counts(Path(WORK_DB), args.project)
    except Exception as exc:
        print("cannot read the ledger for %s: %s" % (args.project, exc), file=sys.stderr)
        return 1

    new = [i for i in to_file if i["title"] not in live]
    already = [i for i in to_file if i["title"] in live]

    # 3. coverage gaps, both directions. Reported, never filed.
    all_doc_keys: set = set()
    for keys in doc_keys.values():
        all_doc_keys |= keys
    unmapped = [b for b in unchecked if b["key"] not in by_key]
    mapped_not_in_doc = [i for i in mapping["items"] if norm_key(i["key"]) not in all_doc_keys]

    # 3b. THE SUPPLY MUST RENEW ITSELF. A mapping file is authored by hand, so a project whose
    # roadmap outruns its mappings starves exactly the way this source was written to prevent -
    # measured 2026-10-07, hours after the first batch: 20 items queued against 47 unchecked
    # boxes, i.e. 26 boxes that would go nowhere once the queue drained. So while boxes exist that
    # have no filed mapping, ONE item is kept open asking for the next batch of mappings, with a
    # definition of done that is mechanically checkable (the validator, the selfcheck, and a
    # counting run). It is filed with a stable subject-shaped title, so the ledger's own title
    # dedup makes it appear once no matter how often this source runs. Item 421 (2026-10-16): the
    # boxes that count are computed by compute_uncovered below - a `not_filed` row that carries its
    # recorded reason is authored, not uncovered, so the renewal item can actually be satisfied.
    uncovered = compute_uncovered(unchecked, by_key, live)
    authoring_title = "Roadmap supply: author the next batch of definitions of done for %s" % args.project

    filed: list[str] = []
    for it in new[: args.limit]:
        ok, note = work_add(args.project, it, args.dry_run)
        if ok:
            filed.append(it["title"])
        else:
            print("FAILED to file %r: %s" % (it["title"], note), file=sys.stderr)

    authoring_open = authoring_title in live
    if uncovered and not authoring_open and not args.no_authoring_item:
        item = {
            "title": authoring_title,
            "why": ("%d unchecked box(es) in %s have no filed mapping row with a runnable "
                    "definition of done, so nothing will claim them once the current queue "
                    "drains. This item is what keeps the supply renewable: it is filed by "
                    "roadmap-supply.py whenever uncovered boxes exist and no authoring item is "
                    "already open, and the ledger's title dedup keeps it to one."
                    % (len(uncovered), ", ".join(mapping.get("source_docs", [])))),
            "dod": AUTHORING_DOD.format(project=args.project,
                                             manifest=str(HERE / ("roadmap-%s.json" % args.project)),
                                             source=str(HERE / "roadmap-supply.py")),
            "priority": args.authoring_priority,
        }
        ok, note = work_add(args.project, item, args.dry_run)
        if ok:
            filed.append(authoring_title)
        else:
            print("FAILED to file the authoring item: %s" % note, file=sys.stderr)

    # A FILED row whose host is not in the capability matrix is an item nobody can run: the matrix
    # is the record of what each host can prove, so a host name it does not carry was invented by
    # the author. Reported every run rather than fixed silently, because the alternative - filing it
    # and learning when a shift stalls - is the failure this whole source exists to end.
    known_hosts = {k for k in (mapping.get("capability_matrix") or {}) if not k.startswith("_")}
    bad_hosts = [(i["key"][:40], i.get("host")) for i in mapping.get("items", [])
                 if i.get("status") == "filed" and known_hosts and i.get("host") not in known_hosts]
    for k, h in bad_hosts:
        print("  BAD-HOST %r names %r, which the capability_matrix does not list" % (k, h),
              file=sys.stderr)

    # The capability matrix is named in the summary line on purpose: the log is where a human
    # reads this source, and the matrix is what stops an author writing a dod no host can run.
    print("%s: hosts=%s unchecked_boxes=%d mapped=%d new=%d filed_this_run=%d already=%d "
          "unmapped_boxes=%d stale_mapping_rows=%d uncovered=%d bad_hosts=%d authoring_item=%s "
          "ledger=%s%s"
          % (SOURCE,
             ",".join(sorted(k for k in (mapping.get("capability_matrix") or {})
                             if not k.startswith("_"))),
             len(unchecked), len(matched), len(new), len(filed), len(already),
             len(unmapped), len(mapped_not_in_doc), len(uncovered), len(bad_hosts),
             "open" if (authoring_open or (uncovered and not args.no_authoring_item)) else "not-needed",
             ",".join("%s:%d" % (k, counts[k]) for k in sorted(counts)) or "empty",
             " DRY-RUN" if args.dry_run else ""))
    for t in filed:
        print("  filed: %s" % t)
    for i in already:
        print("  live:  #%s [%s] %s" % (live[i["title"]][0], live[i["title"]][1], i["title"]))
    for b in unmapped:
        print("  NOT-MAPPED %s:%d  %s" % (b["src"], b["line"], b["text"][:110]), file=sys.stderr)
    for i in mapped_not_in_doc:
        print("  STALE-MAPPING row whose checkbox no longer exists: %r" % i["key"], file=sys.stderr)
    if (not new and not unmapped and not mapped_not_in_doc and not already
            and not uncovered):
        print("quiet")
    return 0


def selfcheck() -> int:
    """Assertions over the pure logic. No store, no docs, no network."""
    fails = []

    def eq(got, want, what):
        if got != want:
            fails.append("%s: got %r want %r" % (what, got, want))

    eq(norm_key("**W-BACK-058** Password reset (single-use, expiring) - a parent who forgets"),
       norm_key("w-back-058 password reset (single-use, expiring) - a parent who forgets"),
       "bold markers and case do not change the key")
    eq(norm_key("- [ ] PIR server setup alongside broker"), "pir server setup alongside broker",
       "list markers are stripped")
    eq(len(norm_key("x" * 200)), KEY_CHARS, "keys are truncated to KEY_CHARS")
    # A doc line that grew its evidence after the em dash must still match its mapping row.
    a = norm_key("Browser extension — URL inspection, content scripts, native messaging")
    b = norm_key("Browser extension — URL inspection, content scripts, native messaging (ledger item 364, done 2026-10-06; branch x => 16/16)")
    eq(a, b, "appended evidence keeps the key stable")
    m = BOX_RE.match("   - [ ] indented box")
    eq(bool(m) and m.group(1) == " " and m.group(2), "indented box", "indented boxes parse")
    m = BOX_RE.match("- [x] done box")
    eq(bool(m) and m.group(1).lower() == "x", True, "checked boxes parse")
    eq(BOX_RE.match("- not a box"), None, "a plain bullet is not a box")
    # The renewal item's definition of done must itself be mechanically checkable: it has to
    # demand the validator, the selfcheck and a counting run, and it has to forbid an unprovable
    # dod. Asserted rather than trusted, because this string is what a future agent will follow.
    for must in ("--selfcheck", "--dry-run", "unmapped_boxes", "capability_matrix", "not_filed",
                 "FORBIDDEN"):
        if must not in AUTHORING_DOD:
            fails.append("AUTHORING_DOD does not demand %r" % must)
    # The dod audit must still catch a command the row's host cannot run - asserted here because
    # a validator that silently stops validating is worse than none.
    demo = {"capability_matrix": {"h1": {}, "h2": {}},
            "items": [{"key": "good", "status": "filed", "host": "h1",
                       "dod": "run `python3 x.py` and quote it"},
                      {"key": "bad-host", "status": "filed", "host": "nope",
                       "dod": "run it"},
                      {"key": "bare-python", "status": "filed", "host": "h1",
                       "dod": "cd server && python -m pytest -q"},
                      {"key": "not-filed", "status": "not_filed", "host": "nope",
                       "dod": "nothing"}]}
    found = [r[0] for r in audit_dods(demo)]
    for must in ("bad-host", "bare-python"):
        if must not in found:
            fails.append("audit_dods did not flag %r (got %r)" % (must, found))
    if "good" in found or "not-filed" in found:
        fails.append("audit_dods flagged a row it should pass: %r" % found)
    if "git diff --stat" not in AUTHORING_DOD:
        fails.append("AUTHORING_DOD does not demand a diffstat")
    # The live dod must render with real paths: a placeholder left in place would send an agent
    # looking for a file named {manifest}, and the whole point of this item is that it is
    # self-contained.
    rendered = AUTHORING_DOD.format(project="p", manifest="/m.json", source="/s.py")
    for must in ("/m.json", "/s.py", "--project p"):
        if must not in rendered:
            fails.append("AUTHORING_DOD does not render %r" % must)
    if "{" in rendered or "}" in rendered:
        fails.append("AUTHORING_DOD leaves an unformatted placeholder")
    # Item 421 (2026-10-16): a `not_filed` row that carries its recorded reason is AUTHORED, not
    # uncovered, so the renewal item can be satisfied instead of refiling itself forever. Only a
    # box with no row at all, a `filed` row whose item is not live, and an unexplained `not_filed`
    # row are gaps. Asserted rather than trusted, because a regression here silently resurrects a
    # self-renewing item that spends a shift per cycle.
    nf_why = {"key": "a", "status": "not_filed", "why": "needs the owner's spend decision"}
    nf_bare = {"key": "b", "status": "not_filed", "why": "   "}
    filed_live = {"key": "c", "status": "filed", "title": "T-c"}
    filed_gone = {"key": "d", "status": "filed", "title": "T-d"}
    mkbox = lambda k: {"key": k, "text": k, "line": 1, "checked": False}
    cu = compute_uncovered([mkbox(k) for k in "abcde"],
                           {i["key"]: i for i in (nf_why, nf_bare, filed_live, filed_gone)},
                           {"T-c": (1, "todo")})
    eq(sorted(b["key"] for b in cu), ["b", "d", "e"],
       "uncovered = no row (e) + filed row whose item is not live (d) + not_filed with a blank "
       "reason (b); a not_filed row WITH its reason (a) and a live filed row (c) are authored")
    cu2 = compute_uncovered([mkbox(k) for k in "ac"], {"a": nf_why, "c": filed_live},
                            {"T-c": (1, "todo")})
    eq(cu2, [], "a project whose every gap is authored or live reports uncovered=0")
    if fails:
        for f in fails:
            print("FAIL %s" % f)
        return 1
    print("roadmap-supply selfcheck: %d pure-logic assertions, 0 failed" % (8 + 10))
    return 0


def check_projects() -> int:
    found = sorted(p.name[len("roadmap-"):-len(".json")] for p in HERE.glob("roadmap-*.json"))
    for pid in found:
        print("%s" % pid)
    if not found:
        print("no roadmap-*.json mapping files in %s" % HERE, file=sys.stderr)
        return 1
    return 0


# Command shapes and the host that can run them. Kept beside the matrix because the two answer
# the same question one layer apart: the matrix says which host can prove what, and this says
# whether the row's own command matches that host. Measured 2026-10-07: the authority has no
# `python` binary, so a bare `python -m pytest` in a dod is unrunnable there - the correction
# was to every project venv's own interpreter.
_DOD_COMMANDS = (
    (re.compile(r"\bdotnet test\b"), "dotnet test", {"zabz-tech-ts", "zabz-yoga-ts"}),
    (re.compile(r"\./gradlew\b"), "gradlew", {"zabz-yoga-ts"}),
    (re.compile(r"\bnpm test\b"), "npm test", {"zabz-tech-ts", "zabz-yoga-ts"}),
    (re.compile(r"\bswift (build|test)\b"), "swift", {"mac-mini-ts"}),
    (re.compile(r"\bplutil\b"), "plutil", {"mac-mini-ts"}),
    # The venv form is matched FIRST and the bare form only when `python` starts a command -
    # after a backtick, or at the start of the text. Measured 2026-10-07: a lookbehind on
    # [\w.] let the bare pattern match inside ".venv/bin/python", which reported thirteen good
    # rows as broken and buried the two real ones. A validator's false positives are worse than
    # no validator, because they train the reader to ignore it.
    (re.compile(r"\.venv/bin/python -m pytest"), ".venv/bin/python -m pytest",
     {"authority", "zabz-tech-ts", "zabz-yoga-ts", "mac-mini-ts"}),
    (re.compile(r"(?:^|`|\s)python -m pytest\b"), "BARE python -m pytest", set()),
)


def audit_dods(mapping: dict) -> list:
    """[(row, host, [problems])] for every FILED row whose command its host cannot run."""
    hosts = {k for k in (mapping.get("capability_matrix") or {}) if not k.startswith("_")}
    out = []
    for it in mapping.get("items", []):
        if it.get("status") != "filed":
            continue
        host = it.get("host")
        dod = it.get("dod") or ""
        problems = []
        if hosts and host not in hosts:
            problems.append("host %r is not in the capability matrix" % host)
        for pat, label, allowed in _DOD_COMMANDS:
            if pat.search(dod):
                if host not in allowed:
                    problems.append("%s cannot run on %s (allowed: %s)"
                                    % (label, host, ",".join(sorted(allowed))))
        if problems:
            out.append((it.get("key", "")[:44], host, problems))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--project", help="project id, e.g. kosher-ai-filter")
    ap.add_argument("--repo", help="override the project's repo path")
    ap.add_argument("--limit", type=int, default=3, help="new items to file per run (default 3)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-authoring-item", action="store_true",
                    help="do not file the supply-renewal item even when uncovered boxes exist")
    ap.add_argument("--authoring-priority", type=int, default=4,
                    help="priority of the supply-renewal item (default 4)")
    ap.add_argument("--selfcheck", action="store_true")
    ap.add_argument("--check-projects", action="store_true")
    ap.add_argument("--audit-dods", action="store_true",
                    help="check every filed row's proving command against the host it names")
    args = ap.parse_args()
    if args.selfcheck:
        return selfcheck()
    if args.check_projects:
        return check_projects()
    if args.audit_dods:
        mapping = load_mapping(HERE / ("roadmap-%s.json" % args.project))
        bad = audit_dods(mapping)
        filed = sum(1 for i in mapping.get("items", []) if i.get("status") == "filed")
        print("dod audit for %s: %d filed row(s), %d with a problem" % (args.project, filed, len(bad)))
        for row, host, problems in bad:
            print("  %-44s host=%-13s %s" % (row, host, "; ".join(problems)))
        return 1 if bad else 0
    if not args.project:
        ap.error("--project is required (or --selfcheck / --check-projects)")
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
