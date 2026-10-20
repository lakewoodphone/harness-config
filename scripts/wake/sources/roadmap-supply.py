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
  * Never refiles a box whose item is DONE. A title that the ledger records as `done` while the
    source doc's box is still unchecked is a landing/doc mismatch (shifts read `origin/main`; the
    checkbox lands on an unmerged branch), so it is REPORTED as `done_not_landed` on stdout and
    not filed again. Measured 2026-10-16: 441 refiled 432 twenty-nine minutes after 432 went done,
    and five more pairs did the same before this rule existed.
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

# A project whose checkout is DECLARED REMOTE-ONLY still has to be readable, or this sensor fails
# every tick and the project starves. Measured 2026-10-16 (work ledger item 383): for
# kosher-ai-filter the registry `repo` is /home/zabz/repos/kosher-filter-ai, which does not exist on
# the authority, and creating a clone there is FORBIDDEN - checkout-health (ledger item 137) honours
# the remote-only declaration only while that path is absent, so a clone would silently retire the
# declaration and make the health check measure a stale copy instead of the real working tree.
# The mapping file may therefore carry `source_git` {url, ref, ...}; the docs are then read with
# `git show` out of a shallow bare cache under CACHE_DIR that checkout-health does not look at.
# Raw https is NOT enough: this repo is private (unauthenticated api.github.com/repos/... -> 404),
# so raw.githubusercontent.com answers 404; git's own transport carries the credentials that are
# already configured for the declared checkout host (`credential.helper=store`). No token is read
# or written here.
CACHE_DIR = Path(os.environ.get("ROADMAP_SUPPLY_CACHE") or "/var/cache/roadmap-supply")
GIT_TIMEOUT = int(os.environ.get("ROADMAP_SUPPLY_GIT_TIMEOUT") or "120")

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


def parse_box_text(text: str) -> list[dict]:
    """Every checkbox in one doc's TEXT, with its 1-based line number, key and checked flag."""
    out: list[dict] = []
    for i, line in enumerate(text.splitlines(), 1):
        m = BOX_RE.match(line)
        if not m:
            continue
        out.append({"line": i, "checked": m.group(1).lower() == "x",
                    "text": m.group(2).strip(), "key": norm_key(m.group(2))})
    return out


def parse_boxes(path: Path) -> list[dict]:
    """Every checkbox in one LOCAL doc file (kept for callers that already hold a Path)."""
    return parse_box_text(path.read_text(encoding="utf-8", errors="replace"))


class LocalDocs:
    """Source docs read straight off a checkout that exists on this host."""
    kind = "local"

    def __init__(self, root: Path):
        self.root = root

    def where(self, rel: str) -> str:
        return str(self.root / rel)

    def read(self, rel: str):
        p = self.root / rel
        if not p.exists():
            return None
        return p.read_text(encoding="utf-8", errors="replace")


class GitDocs:
    """Source docs read out of a shallow bare clone of a REMOTE checkout.

    The cache is deliberately NOT the registry `repo` path: for a remote-only checkout that path
    must stay absent or the declaration that keeps checkout-health honest expires. See CACHE_DIR.
    """

    kind = "git"

    def __init__(self, url: str, ref: str, cache: Path):
        self.url = url
        self.ref = ref or "HEAD"
        self.cache = cache
        self.commit = None

    def _run(self, argv: list, what: str) -> str:
        p = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=GIT_TIMEOUT)
        if p.returncode != 0:
            raise RuntimeError("%s failed (rc=%d): %s"
                               % (what, p.returncode,
                                  " ".join(((p.stdout or "") + (p.stderr or "")).split())[:300]))
        return p.stdout or ""

    def prepare(self) -> None:
        """Clone or refresh the cache, then pin the exact commit the docs are read from."""
        if not self.cache.exists():
            self.cache.parent.mkdir(parents=True, exist_ok=True)
            self._run(["git", "clone", "--bare", "--depth", "1", "--no-tags", "-q",
                       self.url, str(self.cache)], "clone")
            rev = "HEAD"
        else:
            # An existing cache is REFRESHED, never trusted as-is: a sensor that reads last week's
            # roadmap and calls it healthy is the silent wrong answer this whole file exists to end.
            self._run(["git", "-C", str(self.cache), "fetch", "-q", "--depth", "1",
                       "--no-tags", "origin", self.ref], "fetch")
            rev = "FETCH_HEAD"
        self.commit = self._run(["git", "-C", str(self.cache), "rev-parse", rev],
                                "rev-parse %s" % rev).strip()

    def where(self, rel: str) -> str:
        return "%s@%s:%s" % (self.url, (self.commit or self.ref)[:12], rel)

    def read(self, rel: str):
        """The doc's text at the pinned commit, or None when that path is not in the tree."""
        try:
            return self._run(["git", "-C", str(self.cache), "show",
                              "%s:%s" % (self.commit, rel)], "show %s" % rel)
        except RuntimeError as exc:
            # `git show` exits non-zero BOTH for "path not in tree" and for a real transport
            # fault. Only the first is a missing doc; re-raise anything else so a broken cache is
            # reported as a broken cache and not as a roadmap that lost a file.
            msg = str(exc)
            if "does not exist" in msg or "exists on disk, but not in" in msg \
                    or "unknown revision" in msg or "invalid object name" in msg \
                    or "Path '" in msg:
                return None
            raise


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


def ledger_done(db: Path, project: str) -> dict:
    """{exact title: newest DONE item id} for every done item of this project.

    Ledger item 447, measured 2026-10-16: roadmap-supply deduped only against LIVE_STATES, and
    this project's docs are read from origin/main while shifts work on unmerged branches, so a
    box checked only on a branch stays unchecked in the doc the source reads. When its ledger
    row went `done` the title fell out of the live view and the next run refiled it byte for
    byte: 441 was 432 refiled 29 minutes later, and 450/474/480/487/494/500/502/514 repeated it.
    A `done` title is therefore a fact the filing decision needs, not just a live one.
    """
    if not db.exists():
        raise FileNotFoundError("ledger not found: %s" % db)
    c = sqlite3.connect("file:%s?mode=ro" % db, uri=True, timeout=20.0)
    c.row_factory = sqlite3.Row
    try:
        rows = c.execute(
            "SELECT id, title FROM work_item WHERE project=? AND state='done' ORDER BY id",
            (project,)).fetchall()
        return {r["title"]: r["id"] for r in rows}
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


def with_pending(live: dict, titles) -> dict:
    """The live view as it stands at the END of a run: rows this run files count as live.

    Ledger items 447/475, measured 2026-10-16: `uncovered` used to be computed before the new[]
    filing loop against a pre-run `live` snapshot, so a `filed` row whose ledger item this very
    run was about to create still looked filed-but-not-live, and a false supply-renewal item was
    filed in the same second as the real roadmap item. Counting pending titles as live makes
    --dry-run agree with the real run. Pure function, so the selfcheck asserts it.
    """
    out = dict(live)
    for t in titles:
        out.setdefault(t, ("pending", "todo"))
    return out


def compute_uncovered(unchecked: list, by_key: dict, live: dict, settled=()) -> list:
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

    Ledger item 447: `settled` is the set of titles this run reported as done_not_landed. Such a
    box HAS a filed row and a done ledger item; it is a landing/doc mismatch to surface, not a
    box without a definition of done, so it must not also trigger the supply-renewal item.
    """
    settled = set(settled)
    out = []
    for b in unchecked:
        it = by_key.get(b["key"])
        if it is None:
            out.append(b)
            continue
        status = it.get("status")
        if status == "filed":
            if it.get("title") not in live and it.get("title") not in settled:
                out.append(b)
        elif status == "not_filed":
            if not str(it.get("why") or "").strip():
                out.append(b)
        else:
            out.append(b)
    return out


def split_candidates(to_file: list, live: dict, done: dict) -> tuple:
    """Partition the decided rows into (new, already, done_not_landed).

    Ledger item 447, measured 2026-10-16: the watchdog row's ledger item 432 was `done` at
    04:11:12Z while the roadmap box stayed unchecked in origin/main, and 441 refiled it at
    04:37:01Z. `new` is therefore decided with BOTH facts: a title the ledger has ever closed
    `done` is never filed again, and it is reported instead.

    The three groups are disjoint:
      * done_not_landed - the title has a done item and NO todo/running work. Nothing will cover
        the box, so it is a mismatch a person has to resolve (tick the doc box, or reopen).
        A `blocked` row does not count as coverage: blocked is waiting on someone else.
      * already - live work exists (todo, running, or a legitimately blocked row).
      * new - neither live nor done, so it is real unclaimed work.

    Pure function, no store, so the selfcheck asserts the watchdog case.
    """
    new, already, done_not_landed = [], [], []
    for it in to_file:
        title = it["title"]
        state = live[title][1] if title in live else None
        if title in done and state not in ("todo", "running"):
            done_not_landed.append(it)
        elif title in live:
            already.append(it)
        else:
            new.append(it)
    return new, already, done_not_landed


def parse_item_front(text: str, rid: str) -> dict:
    """The four fields this source needs from a roadmap item file, and nothing else.

    Added 2026-10-20 (ledger 795). The item file is the owner of a path's state; the mapping row is
    only the ledger's filing record. Reading the whole file here would make the source depend on prose.
    """
    parts = text.split("---", 2)
    front = parts[1] if len(parts) > 2 else ""
    out = {"id": rid}
    for line in front.splitlines():
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        k = k.strip()
        if k in ("state", "dod", "ledger", "title", "blocked-on"):
            out[k] = v.strip()
    return out


def check_ids(mapping: dict, docs) -> int:
    """Every mapping row's roadmap_id must resolve to an item file that declares that id.

    Added 2026-10-20 (ledger 795). Until now a mapping row identified its path only by the TEXT of a
    checkbox, so a reworded box orphaned the row in silence - measured 2026-10-20: 6 of 47 rows were
    already orphaned that way. A stable id cannot be reworded, but an id nothing verifies is a second
    spelling rather than an identifier, so this is the half that makes it real.
    """
    wanted: dict[str, list] = {}
    for it in mapping.get("items", []):
        rid = str(it.get("roadmap_id") or "").strip()
        if rid:
            wanted.setdefault(rid, []).append(it.get("key"))
    total = len(mapping.get("items", []))
    if not wanted:
        print("check-ids: no row carries a roadmap_id - the mapping has not been migrated", file=sys.stderr)
        return 1
    missing, mismatched = [], []
    for rid in sorted(wanted):
        rel = "docs/roadmap/items/%s.md" % rid
        text = docs.read(rel)
        if text is None:
            missing.append((rid, rel))
            continue
        parts = text.split("---", 2)
        front = parts[1] if len(parts) > 2 else ""
        if not re.search(r"^id:\s*%s\s*$" % re.escape(rid), front, re.MULTILINE):
            mismatched.append((rid, rel))
    id_rows = sum(len(v) for v in wanted.values())
    print("check-ids: %d row(s) carry a roadmap_id over %d distinct id(s); %d row(s) of %d still keyed on "
          "checkbox text alone" % (id_rows, len(wanted), total - id_rows, total))
    for rid, rel in missing:
        print("  MISSING   %-12s %s" % (rid, rel))
    for rid, rel in mismatched:
        print("  MISMATCH  %-12s %s does not declare this id" % (rid, rel))
    if missing or mismatched:
        print("check-ids: FAILED - %d missing, %d mismatched" % (len(missing), len(mismatched)))
        return 1
    print("check-ids: OK - every roadmap_id resolves to an item file that declares it")
    return 0


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
    docs = None
    if repo and repo.exists():
        docs = LocalDocs(repo)
    else:
        git_spec = proj.get("source_git") or mapping.get("source_git") or {}
        if isinstance(git_spec, str):
            git_spec = {"url": git_spec}
        url = args.repo_url or git_spec.get("url")
        if not url:
            print("cannot read the project repo for %s: %r (no local checkout on this host and "
                  "the mapping file names no source_git url)" % (args.project, str(repo)),
                  file=sys.stderr)
            return 1
        docs = GitDocs(str(url), str(git_spec.get("ref") or "HEAD"),
                       CACHE_DIR / ("%s.git" % args.project))
        try:
            docs.prepare()
        except Exception as exc:
            print("cannot read the project repo for %s: %r is absent on this host and the git "
                  "fallback %s failed: %s" % (args.project, str(repo), url, exc), file=sys.stderr)
            return 1

    if getattr(args, "check_ids", False):
        return check_ids(mapping, docs)

    # 1. document direction: unchecked boxes, checked boxes, and the mapping match.
    doc_keys: dict[str, set] = {}
    unchecked: list[dict] = []
    for rel in mapping.get("source_docs", []):
        text = docs.read(rel)
        if text is None:
            print("source doc missing: %s" % docs.where(rel), file=sys.stderr)
            return 1
        boxes = parse_box_text(text)
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

    # 2026-10-20 (ledger 795): a row that carries a roadmap_id is decided by the ITEM FILE's state,
    # not by whether its checkbox is still unchecked. That removes the two blind spots measured on
    # 2026-10-20: a reworded box orphaned its mapping row (6 rows), and a finished path whose box was
    # never ticked looked open for ever (12 rows). A row with no id keeps the old checkbox path, so a
    # project whose roadmap has not been migrated behaves exactly as it did before.
    doc_key_set: set = set()
    for keys in doc_keys.values():
        doc_key_set |= keys
    id_state: dict[str, dict] = {}
    id_counts = {"done": 0, "blocked": 0, "dropped": 0, "open": 0, "partial": 0, "unknown": 0}
    matched: set[str] = set()
    to_file: list[dict] = []
    id_keyed = 0
    for it in mapping["items"]:
        rid = str(it.get("roadmap_id") or "").strip()
        if not rid:
            continue
        id_keyed += 1
        if rid not in id_state:
            item_text = docs.read("docs/roadmap/items/%s.md" % rid)
            if item_text is None:
                print("roadmap item missing for %s: docs/roadmap/items/%s.md" % (rid, rid),
                      file=sys.stderr)
                return 1
            id_state[rid] = parse_item_front(item_text, rid)
        row = id_state[rid]
        state = str(row.get("state") or "").strip()
        id_counts[state if state in id_counts else "unknown"] += 1
        # `matched` stays what it always was - unchecked boxes this source matched - because
        # compute_uncovered() subtracts it from the unchecked set. Counting every id-keyed row here
        # made mapped=41 against 26 unchecked boxes and manufactured uncovered=10, which would have
        # filed a spurious authoring item on the next real run (measured 2026-10-20, dry-run).
        if it.get("status") != "filed":
            continue
        # done, blocked and dropped are paths the roadmap has already decided; nothing to file.
        if state in ("done", "blocked", "dropped"):
            continue
        # open or partial: a candidate. The mapping row's title stays the ledger key, because that is
        # what existing items were filed under and dedup is by exact title; the item file supplies the
        # definition of done, which is the thing that is actually proven.
        to_file.append({**it,
                        "dod": str(row.get("dod") or it.get("dod") or ""),
                        "src": "docs/roadmap/items/%s.md" % rid,
                        "line": 0})

    # Rows with no roadmap_id: the checkbox path, unchanged.
    for box in unchecked:
        it = by_key.get(box["key"])
        if it is None or str(it.get("roadmap_id") or "").strip():
            continue
        matched.add(box["key"])
        if it.get("status") != "filed":
            continue
        to_file.append({**it, "src": box["src"], "line": box["line"]})
    text_keyed = len(mapping["items"]) - id_keyed

    # A mapped box that is now CHECKED in the doc is done by the docs' own record; nothing to file.
    checked_keys = set()
    for rel in mapping.get("source_docs", []):
        text = docs.read(rel)
        if text is None:
            print("source doc missing: %s" % docs.where(rel), file=sys.stderr)
            return 1
        for b in parse_box_text(text):
            if b["checked"]:
                checked_keys.add(b["key"])
    to_file = [i for i in to_file if norm_key(i["key"]) not in checked_keys]

    # 2. ledger direction: what already exists, what is new, and what the ledger says is DONE
    # while the doc box is still unchecked (item 447 - never refile those).
    try:
        live = ledger_live(Path(WORK_DB), args.project)
        done = ledger_done(Path(WORK_DB), args.project)
        counts = ledger_counts(Path(WORK_DB), args.project)
    except Exception as exc:
        print("cannot read the ledger for %s: %s" % (args.project, exc), file=sys.stderr)
        return 1

    new, already, done_not_landed = split_candidates(to_file, live, done)

    # 3. coverage gaps, both directions. Reported, never filed.
    all_doc_keys: set = set()
    for keys in doc_keys.values():
        all_doc_keys |= keys
    unmapped = [b for b in unchecked if b["key"] not in by_key]
    # 2026-10-20 (ledger 795): a stale checkbox is only a defect for a row that still NEEDS the
    # checkbox to be found. An id-keyed row resolves from its item file whatever the box now says,
    # so counting it here would keep reporting the six orphaned-by-rewording rows for ever.
    mapped_not_in_doc = [i for i in mapping["items"]
                         if norm_key(i["key"]) not in all_doc_keys
                         and not str(i.get("roadmap_id") or "").strip()]

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
    authoring_title = "Roadmap supply: author the next batch of definitions of done for %s" % args.project

    filed: list[str] = []
    for it in new[: args.limit]:
        ok, note = work_add(args.project, it, args.dry_run)
        if ok:
            filed.append(it["title"])
        else:
            print("FAILED to file %r: %s" % (it["title"], note), file=sys.stderr)

    # Items 447/475, measured 2026-10-16T09:07:02Z: compute `uncovered` AFTER this run files its own
    # new[] rows, and count those rows as live. Before the fix `uncovered` was computed before the
    # loop that files them, against a `live` snapshot read earlier still, so a `filed` row whose
    # ledger item this very run was about to create looked filed-but-not-live. Measured: that run
    # filed roadmap item 474 and the supply-renewal item 475 in the SAME SECOND, and every earlier
    # cycle did the same (391, 422, 442, 451) - five shifts re-reading a mapping file that was
    # already complete (the very next run reports uncovered=0).
    # 2026-10-20 (ledger 795): coverage is a question about BOXES, and an id-keyed row is no
    # longer resolved by one. Its path exists as an item file whatever the box says, so passing
    # those boxes in computed uncovered=10 the moment the switch landed - ten filed rows whose
    # ledger item is neither live nor done, which the old code masked by marking every one of them
    # pending. They are not uncovered; they are the seven rows that lost their ledger link to a
    # reworded title plus the dropped ones, and their item files already say done or blocked.
    text_only = [b for b in unchecked if not str((by_key.get(b["key"]) or {}).get("roadmap_id") or "").strip()]
    uncovered = compute_uncovered(text_only, by_key, with_pending(live, filed),
                                  settled=[i["title"] for i in done_not_landed])

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
    print("%s: docs=%s hosts=%s unchecked_boxes=%d mapped=%d new=%d filed_this_run=%d already=%d "
          "done_not_landed=%d unmapped_boxes=%d stale_mapping_rows=%d uncovered=%d bad_hosts=%d "
          "id_keyed=%d text_keyed=%d item_state=%s authoring_item=%s ledger=%s%s"
          % (SOURCE,
             docs.kind,
             ",".join(sorted(k for k in (mapping.get("capability_matrix") or {})
                             if not k.startswith("_"))),
             len(unchecked), len(matched), len(new), len(filed), len(already),
             len(done_not_landed), len(unmapped), len(mapped_not_in_doc), len(uncovered),
             len(bad_hosts), id_keyed, text_keyed,
             ",".join("%s:%d" % (k, v) for k, v in sorted(id_counts.items()) if v) or "empty",
             "open" if (authoring_open or (uncovered and not args.no_authoring_item)) else "not-needed",
             ",".join("%s:%d" % (k, counts[k]) for k in sorted(counts)) or "empty",
             " DRY-RUN" if args.dry_run else ""))
    for t in filed:
        print("  filed: %s" % t)
    for i in done_not_landed:
        print("  DONE-NOT-LANDED #%s %s (box %s:%s) - ledger item is done, the doc box is still "
              "unchecked; NOT refiled" % (done[i["title"]], i["title"], i.get("src"),
                                          i.get("line", "?")))
    for i in already:
        print("  live:  #%s [%s] %s" % (live[i["title"]][0], live[i["title"]][1], i["title"]))
    for b in unmapped:
        print("  NOT-MAPPED %s:%d  %s" % (b["src"], b["line"], b["text"][:110]), file=sys.stderr)
    for i in mapped_not_in_doc:
        print("  STALE-MAPPING row whose checkbox no longer exists: %r" % i["key"], file=sys.stderr)
    if (not new and not unmapped and not mapped_not_in_doc and not already
            and not uncovered and not done_not_landed):
        print("quiet")
    return 0


def selfcheck() -> int:
    """Assertions over the pure logic. No store, no docs, no network."""
    fails = []
    checks = [0]

    def eq(got, want, what):
        checks[0] += 1
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
    # The remote-docs fallback (2026-10-16, ledger item 383) must join a repo-relative path onto
    # the REMOTE and pin the commit it read, and the text parser must work without a Path - both
    # asserted because the whole point of the fallback is a host that has no checkout to read.
    gd = GitDocs("https://example.invalid/r.git", "HEAD", Path("/tmp/roadmap-supply-nope.git"))
    gd.commit = "a" * 40
    eq(gd.where("docs/x.md"), "https://example.invalid/r.git@" + "a" * 12 + ":docs/x.md",
       "GitDocs.where names the remote, the pinned commit and the doc path")
    eq([b["key"] for b in parse_box_text("- [ ] a box\n- [x] done box\ntext")],
       ["a box", "done box"], "parse_box_text reads boxes out of text, not a path")
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
    # Items 447/475 (2026-10-16): a `filed` row whose ledger item THIS RUN is about to create must
    # not be counted uncovered. Measured: the 09:07:02Z run filed 474 then 475 in the same second.
    eq(compute_uncovered([mkbox("z")], {"z": filed_gone}, with_pending({}, ["T-d"])), [],
       "a filed row whose item this run files is NOT uncovered once its title counts as pending-live")
    # Item 447, measured 2026-10-16: 432 went done while the watchdog box stayed unchecked in
    # origin/main, and 441 refiled it 29 minutes later and was then parked `blocked` as a dedupe
    # guard. A done title must NEVER be refiled. It is reported as done_not_landed when nothing
    # active covers the box (a blocked guard does not cover it), stays `already` when todo/running
    # work does, and must not also trigger the supply-renewal item.
    wd_done = {"T-d": 432}
    n, a, d = split_candidates([{"title": "T-d", "key": "z"}], {"T-d": (441, "blocked")}, wd_done)
    eq((n, [i["title"] for i in a], [i["title"] for i in d]), ([], [], ["T-d"]),
       "447: the watchdog row (item done, box unchecked, only a blocked guard) is "
       "done_not_landed and never new")
    n, a, d = split_candidates([{"title": "T-d"}], {"T-d": (450, "todo")}, wd_done)
    eq((n, [i["title"] for i in a], d), ([], ["T-d"], []),
       "447: a done title with active todo work is already, not double-counted")
    n, a, d = split_candidates([{"title": "T-d"}], {}, wd_done)
    eq((n, [i["title"] for i in a], [i["title"] for i in d]), ([], [], ["T-d"]),
       "447: a done title with nothing live is done_not_landed and never new")
    n, a, d = split_candidates([{"title": "T-c"}], {"T-c": (1, "todo")}, {})
    eq((n, [i["title"] for i in a], d), ([], ["T-c"], []), "447: ordinary live work is already")
    n, a, d = split_candidates([{"title": "T-e"}], {}, {})
    eq(([i["title"] for i in n], a, d), (["T-e"], [], []), "447: ordinary unclaimed work is new")
    box_z = mkbox("z")
    eq(compute_uncovered([box_z], {"z": filed_gone}, {}, settled=["T-d"]), [],
       "447: a done_not_landed box is settled, so it does not raise a supply-renewal item")
    eq(len(compute_uncovered([box_z], {"z": filed_gone}, {})), 1,
       "447: without the settlement the same box is a gap")
    if fails:
        for f in fails:
            print("FAIL %s" % f)
        return 1
    print("roadmap-supply selfcheck: %d eq checks + dod/audit assertions, 0 failed" % checks[0])
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
    ap.add_argument("--repo-url", help="override the git remote the source docs are read from "
                                       "when no local checkout exists (see mapping source_git)")
    ap.add_argument("--limit", type=int, default=3, help="new items to file per run (default 3)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-authoring-item", action="store_true",
                    help="do not file the supply-renewal item even when uncovered boxes exist")
    ap.add_argument("--authoring-priority", type=int, default=4,
                    help="priority of the supply-renewal item (default 4)")
    ap.add_argument("--selfcheck", action="store_true")
    ap.add_argument("--check-projects", action="store_true")
    ap.add_argument("--check-ids", action="store_true",
                    help="check that every roadmap_id resolves to a roadmap item file")
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
