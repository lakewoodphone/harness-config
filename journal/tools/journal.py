#!/usr/bin/env python3
"""journal.py — the only writer and the cheapest reader of the journal.

The journal is my memory. It is not documentation. Three failures drove this tool
into existence, all measured on 2026-09-14:

  1. It was six flat files totalling 590 KB. Reading them cost ~150k tokens, so
     nobody read them, so the same audits were recommissioned.
  2. IDs were allocated by eye from the last line of a file that had been merged
     from three machines, so PAIN held two different P13/P14/P17/P18/P43..P52 and
     DECISIONS held four different D41s. A cross-reference like "PAIN P46" was
     ambiguous three ways and nothing complained.
  3. State and history were the same document. To learn what was open you read
     1067 lines, most of them closed.

So: the log is append-only and sharded by month; the state tier is small and
rewritten; the index is generated; and the allocator is this program, which takes
the maximum over the index AND every shard AND every remote ref, so two machines
cannot pick the same number twice.

Read path (see journal/README.md):
    journal.py status                 # the always-read page, < 12 KB
    journal.py newest handoff 2       # newest entries of one kind
    journal.py show P46               # one entry
    journal.py search "duplicate id"  # ~50 lines per hit, never whole files
    journal.py check                  # integrity; non-zero exit on error
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Shape of the journal. One place, so the format cannot drift again.
# ---------------------------------------------------------------------------

JOURNAL = Path(__file__).resolve().parent.parent
LOG = JOURNAL / "log"
INDEX = JOURNAL / "index" / "entries.tsv"
STATE = JOURNAL / "state"

KINDS = {
    "handoff": {
        "letter": "H",
        "display": "HANDOFF",
        "heading": "## {date} · {host} · {title}",
        "dated": True,
        # two forms exist in the record: 'date · host · title' and 'date · title'
        "regex": re.compile(r"^## (?P<date>\d{4}-\d{2}-\d{2}[^·\n]*?)(?: · (?P<host>[^·\n]+?) · (?P<title>.+))?$"),
    },
    "lessons": {
        "letter": "L",
        "display": "LESSONS",
        "heading": "**{id} · {title}**",
        "dated": False,
        # no closing ** here on purpose: headings in the old file wrap onto a second line
        "regex": re.compile(r"^\*\*(?P<id>L(?P<num>\d+)) · (?P<title>.+)$"),
    },
    "pain": {
        "letter": "P",
        "display": "PAIN",
        "heading": "## {id} — {title}",
        "dated": False,
        "regex": re.compile(r"^## (?P<id>P(?P<num>\d+))\b[ —–-]*(?P<title>.*)$"),
    },
    "decisions": {
        "letter": "D",
        "display": "DECISIONS",
        "heading": "**{id} · {date} · {title}.**",
        "dated": True,
        "regex": re.compile(r"^\*\*(?P<id>D(?P<num>\d+)) · (?P<date>\d{4}-\d{2}-\d{2}) · (?P<title>.+)$"),
    },
    "wins": {
        "letter": "W",
        "display": "WINS",
        "heading": "**{id} · {date} · {title}.**",
        "dated": True,
        "regex": re.compile(r"^\*\*(?P<id>W(?P<num>\d+)[a-z]?) · (?P<date>\d{4}-\d{2}-\d{2}[^·\n]*) · (?P<title>.+)$"),
    },
}

BOLD_KINDS = {"lessons", "decisions", "wins"}
# lines that look like an entry but are structure, not an entry
NOT_AN_ENTRY = re.compile(r"^(## YYYY|## ⚠)")

LETTER_TO_KIND = {v["letter"]: k for k, v in KINDS.items()}

MARKER_RE = re.compile(r"^<!--\s*e:(?P<kind>[a-z]+)\|(?P<id>[^|]*)\|(?P<date>[^|]*)\|(?P<host>[^|]*)\|(?P<status>[^|]*?)\s*-->\s*$")
SHARD_HEADER_RE = re.compile(r"^#\s+(?P<kind>[a-z]+)\s+·\s+(?P<month>\d{4}-\d{2})\s*$")
H1_RE = re.compile(r"^# ")
SECTION_RE = re.compile(r"^## (?!#)")

MAX_STATUS_CHARS = 12000


def now_utc() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def today() -> str:
    return _dt.date.today().isoformat()


def hostname() -> str:
    return os.environ.get("DSH_HOST") or os.environ.get("COMPUTERNAME") or os.uname().nodename if hasattr(os, "uname") else os.environ.get("COMPUTERNAME", "unknown")


def host_tag() -> str:
    """The machine that wrote an entry — Windows COMPUTERNAME or a POSIX hostname.

    The first version fell back to 'UNKNOWN' on Linux, which would have mislabelled
    every entry written on the authority.
    """
    import socket
    h = os.environ.get("DSH_MACHINE") or os.environ.get("COMPUTERNAME") or ""
    if not h:
        try:
            h = socket.gethostname()
        except Exception:
            h = "unknown"
    return h.split(".")[0].upper()


def norm_body(text: str) -> str:
    """Whitespace-collapsed body, used as the identity of an entry."""
    lines = [ln.rstrip() for ln in text.replace("\r\n", "\n").split("\n")]
    while lines and not lines[-1].strip():
        lines.pop()
    while lines and lines[-1].strip() in {"---", "***"}:
        lines.pop()
        while lines and not lines[-1].strip():
            lines.pop()
    return re.sub(r"[ \t]+", " ", "\n".join(lines)).strip()


def body_hash(body: str) -> str:
    return hashlib.sha1(norm_body(body).encode("utf-8")).hexdigest()[:16]


def entry_hash(heading: str, body: str) -> str:
    """Identity of an entry: heading AND body.

    Body alone is not enough — eight lessons in the old file (L23, L162-L166, L170,
    L173) put the entire lesson on the heading line and have an empty body, so a
    body-only key dropped seven of them on the first migration attempt.
    """
    payload = f"{re.sub(r'[ \t]+', ' ', (heading or '').strip())}\n---\n{norm_body(body)}"
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

class Entry(dict):
    """A journal entry. Duck-typed dict so it survives json round-trips."""


def parse_shard(path: Path, kind: str) -> list[Entry]:
    """Parse a shard that carries markers (everything written from 2026-09-14)."""
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.split("\n")
    starts = [i for i, ln in enumerate(lines) if MARKER_RE.match(ln)]
    entries: list[Entry] = []
    for n, i in enumerate(starts):
        m = MARKER_RE.match(lines[i])
        end = starts[n + 1] if n + 1 < len(starts) else len(lines)
        heading = lines[i + 1].strip() if i + 1 < len(lines) else ""
        body = "\n".join(lines[i + 2:end])
        entries.append(Entry(
            kind=kind,
            id_full=m.group("id"),
            date=m.group("date"),
            host=m.group("host"),
            status=m.group("status"),
            heading=heading,
            body=norm_body(body),
            section="",
            file=str(path.relative_to(JOURNAL)).replace("\\", "/"),
            line_start=i + 1,
            heading_end=i + 2,
            line_end=end,
        ))
    return entries


def parse_legacy(path: Path, kind: str) -> list[Entry]:
    """Parse one of the six flat pre-2026-09-14 files. Used by migrate and audit.

    Bold headings in the old files wrap onto a second line ('**L159 · A 500 from your
    own API ...' / 'must outlast ...**'), so the anchor deliberately does not require a
    closing '**' and the heading is flushed across lines. Missing this silently dropped
    37 entries on the first migration attempt.
    """
    spec = KINDS[kind]
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.split("\n")
    starts: list[tuple[int, re.Match]] = []
    for i, ln in enumerate(lines):
        if NOT_AN_ENTRY.match(ln.strip()):
            continue
        m = spec["regex"].match(ln.strip())
        if m:
            starts.append((i, m))
    entries: list[Entry] = []
    section = ""
    for n, (i, m) in enumerate(starts):
        end = starts[n + 1][0] if n + 1 < len(starts) else len(lines)
        for j in range(i + 1, end):
            if kind == "lessons" and SECTION_RE.match(lines[j]) and not KINDS["pain"]["regex"].match(lines[j].strip()):
                section = lines[j][3:].strip()
        # A bold heading ends at the closing '**' — which may be mid-line (the rest of
        # that line is then body) or on a following line (the old files wrap).
        rest = ""
        heading_end = i
        if kind in BOLD_KINDS:
            j = i
            idx = lines[j].find("**", 2)
            while idx == -1 and j + 1 < end:
                j += 1
                idx = lines[j].find("**")
            if idx == -1:
                heading_end = i
            else:
                heading_end = j
                rest = lines[j][idx + 2:]
        raw_heading = " ".join(ln.strip() for ln in lines[i:heading_end + 1])
        heading = raw_heading
        cut = raw_heading.rfind("**")
        if kind in BOLD_KINDS and cut > 0:
            heading = raw_heading[:cut + 2]
        body_lines = ([rest] if rest.strip() else []) + lines[heading_end + 1:end]
        body = "\n".join(body_lines)
        num = int(m.group("num")) if "num" in m.groupdict() and m.group("num") else None
        entries.append(Entry(
            kind=kind,
            id_full=m.group("id") if "id" in m.groupdict() and m.group("id") else "",
            num=num,
            date=(m.group("date") or "").strip() if "date" in m.groupdict() else "",
            host=(m.group("host") or "").strip() if "host" in m.groupdict() else "",
            status="",
            heading=heading,
            body=norm_body(body),
            section=section,
            file=str(path).replace("\\", "/"),
            line_start=i + 1,
            heading_end=heading_end + 1,
            line_end=end,
        ))
    return entries


def load_shards() -> list[Entry]:
    out: list[Entry] = []
    if not LOG.exists():
        return out
    for path in sorted(LOG.rglob("*.md")):
        kind = path.parent.name
        if kind not in KINDS:
            continue
        out.extend(parse_shard(path, kind))
    return out


def load_index() -> list[dict]:
    if not INDEX.exists():
        return []
    rows = []
    for ln in INDEX.read_text(encoding="utf-8").split("\n"):
        if not ln.strip() or ln.startswith("kind\t"):
            continue
        parts = ln.split("\t")
        if len(parts) < 11:
            continue
        rows.append(dict(zip(
            ["kind", "id_full", "num", "suffix", "date", "host", "status", "heading",
             "file", "line_start", "line_end", "hash"], parts)))
    return rows


def num_of(id_full: str) -> int:
    m = re.search(r"(\d+)", id_full or "")
    return int(m.group(1)) if m else 0


def suffix_of(id_full: str) -> str:
    m = re.match(r"^[A-Z]+\d+(.*)$", id_full or "")
    return m.group(1) if m else ""


# ---------------------------------------------------------------------------
# Index
# ---------------------------------------------------------------------------

INDEX_HEADER = "kind\tid_full\tnum\tsuffix\tdate\thost\tstatus\theading\tfile\tline_start\tline_end\thash"


def cmd_index(args) -> int:
    entries = load_shards()
    events = load_status_events()
    rows = [INDEX_HEADER]
    order = {k: i for i, k in enumerate(KINDS)}
    entries.sort(key=lambda e: (order.get(e["kind"], 9), e["date"] or "", num_of(e["id_full"]), e["line_start"]))
    for e in entries:
        rows.append("\t".join([
            e["kind"], e["id_full"], str(num_of(e["id_full"])), suffix_of(e["id_full"]),
            e["date"] or "-", e["host"] or "-",
            effective_status(e["kind"], e["id_full"], e["status"], events),
            e["heading"], e["file"], str(e["line_start"]), str(e["line_end"]),
            entry_hash(e["heading"], e["body"]),
        ]))
    INDEX.parent.mkdir(parents=True, exist_ok=True)
    INDEX.write_text("\n".join(rows) + "\n", encoding="utf-8", newline="\n")
    print(f"index: {len(rows) - 1} entries -> {INDEX.relative_to(JOURNAL)}")
    return 0


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------

def read_lines(rel_file: str, start: int, end: int) -> str:
    path = JOURNAL / rel_file
    lines = path.read_text(encoding="utf-8", errors="replace").split("\n")
    chunk = lines[start - 1:end]
    while chunk and not chunk[-1].strip():
        chunk.pop()
    while chunk and chunk[-1].strip() in {"---", "***"}:
        chunk.pop()
    return "\n".join(chunk)


def render(entry: dict) -> str:
    head = f"### {entry['id_full']} · {entry['kind']} · {entry['date'] or 'undated'} · {entry['status'] or '-'}"
    body = read_lines(entry["file"], int(entry["line_start"]) + 1, int(entry["line_end"]))
    return f"{head}\n{body}\n"


def cmd_show(args) -> int:
    rows = load_index()
    wanted = args.id.upper()
    hits = [r for r in rows if r["id_full"].upper() == wanted]
    if not hits:
        hits = [r for r in rows if r["id_full"].upper().startswith(wanted)]
    if not hits:
        print(f"no entry {args.id}", file=sys.stderr)
        return 2
    if len(hits) > 1 and not args.all:
        print(f"{len(hits)} entries match {args.id}: " + ", ".join(r["id_full"] for r in hits), file=sys.stderr)
    for r in hits:
        print(render(r))
    return 0


def cmd_newest(args) -> int:
    rows = load_index()
    kind = args.kind
    if kind not in KINDS:
        print(f"unknown kind {kind}; one of {', '.join(KINDS)}", file=sys.stderr)
        return 2
    rows = [r for r in rows if r["kind"] == kind]
    rows.sort(key=lambda r: (r["date"] or "", int(r["num"]), int(r["line_start"])), reverse=True)
    for r in rows[: args.n]:
        print(render(r))
    return 0


def cmd_search(args) -> int:
    pattern = re.compile(args.pattern, re.IGNORECASE)
    roots = [LOG, STATE, JOURNAL / "reference", JOURNAL / "README.md", JOURNAL / "NOW.md"]
    hits = 0
    for root in roots:
        paths = sorted(root.rglob("*.md")) if root.is_dir() else ([root] if root.exists() else [])
        for path in paths:
            lines = path.read_text(encoding="utf-8", errors="replace").split("\n")
            current = ""
            for i, ln in enumerate(lines):
                if MARKER_RE.match(ln) and i + 1 < len(lines):
                    current = lines[i + 1].strip()
                if pattern.search(ln):
                    hits += 1
                    if hits <= args.limit:
                        rel = path.relative_to(JOURNAL) if JOURNAL in path.resolve().parents or path.parent == JOURNAL else path
                        print(f"{rel}:{i + 1}: {current[:90]}\n    {ln.strip()[:200]}")
        if hits > args.limit:
            break
    print(f"-- {hits} matching line(s)" + (f", showing {args.limit}" if hits > args.limit else ""))
    return 0 if hits else 1


def cmd_status(args) -> int:
    rows = load_index()
    out: list[str] = []
    out.append(f"JOURNAL STATUS · {now_utc()} · {host_tag()}")
    now = JOURNAL / "NOW.md"
    if now.exists():
        out.append("")
        out.append(now.read_text(encoding="utf-8", errors="replace").strip())
    handoffs = sorted([r for r in rows if r["kind"] == "handoff"], key=lambda r: (r["date"], int(r["num"])), reverse=True)
    out.append("")
    out.append("NEWEST HANDOFF: " + (handoffs[0]["heading"] if handoffs else "none"))
    out.append("")
    open_pain = [r for r in rows if r["kind"] == "pain" and r["status"] != "done"]
    out.append(f"OPEN PAIN: {len(open_pain)} of {len([r for r in rows if r['kind'] == 'pain'])}")
    for r in open_pain[:8]:
        out.append(f"  {r['id_full']:>6}  {r['heading'][:110]}")
    qrows = []
    qpath = STATE / "owner-questions.md"
    if qpath.exists():
        qtext = qpath.read_text(encoding="utf-8", errors="replace")
        m = re.search(r"(\d+) pending", qtext)
        if m:
            qrows = [None] * int(m.group(1))          # the mirror states the count
        else:
            for ln in qtext.split("\n"):
                if ln.startswith("| ") and not ln.startswith("| #") and "---" not in ln:
                    qrows.append(ln)
        src = re.search(r"generated (\d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC)", qtext)
        prov = f", mirror of {src.group(1)}" if src else ""
    else:
        prov = ""
    out.append("")
    out.append(f"OWNER QUESTIONS OPEN: {len(qrows)}{prov}  (authoritative: owner_decision_queue on the authority)")
    for ln in [r for r in qrows if r][:4]:
        cells = [c.strip() for c in ln.strip("|").split("|")]
        out.append(f"  {cells[0]}  {cells[2][:110] if len(cells) > 2 else ''}")
    inflight = STATE / "in-flight.md"
    if inflight.exists():
        out.append("")
        out.append(inflight.read_text(encoding="utf-8", errors="replace").strip())
    errs = verify(rows, quiet=True)
    out.append("")
    out.append(f"CHECK: {len(errs['error'])} error(s), {len(errs['warn'])} warning(s) — run `journal.py check`")
    text = "\n".join(out)
    print(text)
    if len(text) > MAX_STATUS_CHARS:
        print(f"\n!! status output {len(text)} chars > {MAX_STATUS_CHARS} budget", file=sys.stderr)
        return 1
    return 0


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

REF_RE = re.compile(r"(?<![A-Za-z0-9])([LPDW])(\d{1,3})(?![0-9])")


def verify(rows: list[dict], quiet: bool = False) -> dict:
    problems = {"error": [], "warn": [], "info": []}
    by_kind: dict[str, list[dict]] = {}
    for r in rows:
        by_kind.setdefault(r["kind"], []).append(r)

    # 1. duplicate ids — the failure that made P46 mean three things
    for kind, rs in by_kind.items():
        seen: dict[str, list[dict]] = {}
        for r in rs:
            seen.setdefault(r["id_full"], []).append(r)
        for id_full, group in seen.items():
            if len(group) > 1:
                where = ", ".join(f"{g['file']}:{g['line_start']}" for g in group)
                problems["error"].append(f"duplicate id {id_full} in {kind} ({len(group)}x): {where}")
        hashes: dict[str, list[dict]] = {}
        for r in rs:
            hashes.setdefault(r["hash"], []).append(r)
        for h, group in hashes.items():
            if len(group) > 1:
                problems["warn"].append("duplicate entry (same heading and body) in " + ", ".join(f"{g['id_full']}({g['file']}:{g['line_start']})" for g in group))

    # 2. collision-repaired ids. The rebuild made each repaired number explicit
    #    (P46 / P46b / P46c), so this is no longer an uncaught collision — but a
    #    reference to the bare number in older prose is still ambiguous, and that
    #    is worth saying once per number rather than once per entry.
    for kind, rs in by_kind.items():
        letter = KINDS[kind]["letter"]
        numbers: dict[int, set[str]] = {}
        for r in rs:
            numbers.setdefault(num_of(r["id_full"]), set()).add(r["id_full"])
        collided = sorted((n, ids) for n, ids in numbers.items() if len(ids) > 1)
        if collided:
            names = ", ".join(f"{letter}{n}" for n, _ in collided)
            sample = ", ".join(names.split(", ")[:12])
            problems["warn"].append(
                f"{letter}: {len(collided)} base id(s) name more than one entry ({sample}"
                + (f", +{len(collided) - 12} more" if len(collided) > 12 else "")
                + ") — repaired with suffixes, so a bare reference in older prose is ambiguous. "
                  "Never write a bare id; use the suffixed one from index/entries.tsv.")

    # 3. dangling references (info: prose can look like a reference)
    known = {KINDS[k]["letter"]: {num_of(r["id_full"]) for r in rs} for k, rs in by_kind.items()}
    for path in sorted(JOURNAL.rglob("*.md")):
        if "archive" in path.parts or "tools" in path.parts:
            continue
        for i, ln in enumerate(path.read_text(encoding="utf-8", errors="replace").split("\n")):
            if ln.startswith("<!--"):
                continue
            for m in REF_RE.finditer(ln):
                letter, num = m.group(1), int(m.group(2))
                if letter in known and num not in known[letter] and num > 0:
                    problems["info"].append(f"dangling ref {letter}{num} at {path.relative_to(JOURNAL)}:{i + 1}")

    # 4. shard size and ordering
    for path in sorted(LOG.rglob("*.md")) if LOG.exists() else []:
        size = path.stat().st_size
        if size > 260_000:
            problems["warn"].append(
                f"shard {path.relative_to(JOURNAL)} is {size // 1024} KB — "
                f"`journal.py split-shard {path.relative_to(JOURNAL).as_posix()}`")
        kind = path.parent.name
        ents = parse_shard(path, kind)
        # Two sessions' clocks can disagree by minutes; only gross disorder means a
        # stale append, so allow a quarter hour of backdating before complaining.
        for a, b in zip(ents, ents[1:]):
            if a["date"] and b["date"] and _minute_key(a["date"]) - _minute_key(b["date"]) > 15:
                problems["warn"].append(f"out of order in {path.relative_to(JOURNAL)}: {a['id_full']} ({a['date']}) then {b['id_full']} ({b['date']})")
        if not ents and path.stat().st_size > 400:
            problems["warn"].append(f"{path.relative_to(JOURNAL)} has content but no parseable entries")

    # 5. state tier freshness
    newest_handoff = max((r["date"] for r in by_kind.get("handoff", []) if r["date"]), default="")
    for name in ("NOW.md", "state/open-pain.md", "state/in-flight.md"):
        p = JOURNAL / name
        if not p.exists():
            problems["warn"].append(f"{name} missing")
            continue
        m = re.search(r"(?:Updated|updated)[: ]+(\d{4}-\d{2}-\d{2})", p.read_text(encoding="utf-8", errors="replace"))
        if not m:
            problems["warn"].append(f"{name} has no 'Updated: YYYY-MM-DD' line")
        elif newest_handoff and m.group(1) < newest_handoff[:10]:
            problems["warn"].append(f"{name} says {m.group(1)} but the newest handoff is {newest_handoff[:10]} — state tier is stale")

    # 6. every marker must be followed by a heading
    for path in sorted(LOG.rglob("*.md")) if LOG.exists() else []:
        lines = path.read_text(encoding="utf-8", errors="replace").split("\n")
        for i, ln in enumerate(lines):
            if MARKER_RE.match(ln):
                nxt = lines[i + 1] if i + 1 < len(lines) else ""
                if not nxt.strip():
                    problems["error"].append(f"entry with empty heading at {path.relative_to(JOURNAL)}:{i + 1}")

    # 6b. a marker must start its line. A glued marker (after a missing trailing
    #     newline) silently folds one entry into the previous one's body. Only a whole
    #     marker at the end of a line, preceded by separators, counts — a marker quoted
    #     inside prose (a lesson about this very bug) does not.
    glued = re.compile(r"^[-—─\s]*<!--\s*e:[a-z]+\|[^|]*\|[^|]*\|[^|]*\|[^|]*?-->\s*$")
    for path in sorted(LOG.rglob("*.md")) if LOG.exists() else []:
        for i, ln in enumerate(path.read_text(encoding="utf-8", errors="replace").split("\n")):
            if "<!-- e:" in ln and not MARKER_RE.match(ln) and glued.match(ln):
                problems["error"].append(
                    f"marker does not start its line at {path.relative_to(JOURNAL)}:{i + 1} — "
                    "that entry is being read into the previous one")

    # 7. the retired flat files must not accumulate entries the record lacks.
    #    A second session was writing them at the same time as the rebuild, so this
    #    is the alarm that makes the transition safe rather than hopeful.
    local = {content_key(e["heading"], e["body"]) for e in load_shards()}
    for name, kind in (("HANDOFF", "handoff"), ("LESSONS", "lessons"), ("PAIN", "pain"),
                       ("DECISIONS", "decisions"), ("WINS", "wins")):
        flat = JOURNAL / f"{name}.md"
        if not flat.exists():
            continue
        try:
            ents = parse_legacy(flat, kind)
        except Exception as exc:                     # a file mid-write is not an error
            problems["info"].append(f"{name}.md could not be parsed right now: {exc}")
            continue
        stray = [e for e in ents if content_key(e["heading"], e["body"]) not in local]
        if stray:
            problems["warn"].append(
                f"{name}.md has {len(stray)} entry/entries not in the log (first: "
                f"{stray[0]['heading'][:70]!r}) — run `journal.py import-flat`")

    if not quiet:
        for level in ("error", "warn", "info"):
            for p in problems[level][:60]:
                print(f"{level.upper():5} {p}")
            if len(problems[level]) > 60:
                print(f"{level.upper():5} ... and {len(problems[level]) - 60} more")
        print(f"-- {len(problems['error'])} error(s), {len(problems['warn'])} warning(s), {len(problems['info'])} info")
    return problems


def cmd_check(args) -> int:
    rows = load_index()
    if not rows:
        print("no index — run `journal.py index`", file=sys.stderr)
        return 1
    problems = verify(rows)
    return 1 if problems["error"] else 0


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------

def remote_max(kind: str) -> tuple[int, str]:
    """Highest number for a kind anywhere in git history or on the remote.

    This is what stops two machines allocating the same number: the answer is
    taken over the local index, every shard, and every ref including origin.
    """
    letter = KINDS[kind]["letter"]
    nums: list[int] = []
    # Every pattern is anchored: an id mentioned inside prose (a lesson about a glued
    # marker quotes one) must not consume a number. That happened once and left a gap.
    pattern = (rf"^## {letter}[0-9]+ |^\*\*{letter}[0-9]+ |^<!-- e:{kind}\|{letter}[0-9]+")
    try:
        out = subprocess.run(["git", "-C", str(JOURNAL.parent), "grep", "-h", "-E", pattern],
                             capture_output=True, text=True, timeout=60)
        for m in re.finditer(rf"{letter}(\d+)", out.stdout or ""):
            nums.append(int(m.group(1)))
    except Exception:
        pass
    try:
        revs = subprocess.run(["git", "-C", str(JOURNAL.parent), "rev-list", "--all"],
                             capture_output=True, text=True, timeout=60).stdout.split()
        if revs:
            out = subprocess.run(["git", "-C", str(JOURNAL.parent), "grep", "-h", "-E",
                                 rf"^<!-- e:{kind}\|{letter}[0-9]+"],
                                 capture_output=True, text=True, timeout=120)
            for m in re.finditer(rf"{letter}(\d+)", out.stdout or ""):
                nums.append(int(m.group(1)))
    except Exception:
        pass
    for r in load_index() + load_shards():
        if r.get("kind") == kind:
            nums.append(num_of(r["id_full"]))
    best = max(nums) if nums else 0
    return best, (subprocess.run(["git", "-C", str(JOURNAL.parent), "rev-parse", "--short", "HEAD"],
                                 capture_output=True, text=True).stdout.strip() or "no-git")


def cmd_next_id(args) -> int:
    if args.kind not in KINDS:
        print(f"unknown kind {args.kind}", file=sys.stderr)
        return 2
    best, rev = remote_max(args.kind)
    letter = KINDS[args.kind]["letter"]
    print(f"{letter}{best + 1}")
    print(f"# highest seen: {letter}{best} (across index, shards and git @ {rev})", file=sys.stderr)
    return 0


def build_heading(kind: str, id_full: str, title: str, date: str, host: str) -> str:
    spec = KINDS[kind]
    if kind == "handoff":
        stamp = date or now_utc()
        return f"## {stamp} · {host or host_tag()} · {title}"
    if kind == "lessons":
        return f"**{id_full} · {title}**"
    if kind == "pain":
        return f"## {id_full} — {title}"
    if kind == "decisions":
        return f"**{id_full} · {date or today()} · {title}.**"
    return f"**{id_full} · {date or today()} · {title}.**"


def _minute_key(date: str) -> int:
    """A sortable minute-resolution key from a date like '2026-09-14 05:55 UTC'."""
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})(?:\s+(\d{2}):(\d{2}))?", date or "")
    if not m:
        return 0
    y, mo, d, hh, mm = m.groups()
    return (((int(y) * 12 + int(mo)) * 31 + int(d)) * 24 + int(hh or 0)) * 60 + int(mm or 0)


def _part_num(path: Path) -> int:
    m = re.match(r"^\d{4}-\d{2}\.(\d+)$", path.stem)
    return int(m.group(1)) + 1 if m else 1


def shard_path(kind: str, date: str) -> Path:
    """Where a new entry for this kind and month goes.

    A month is one file until it crosses the cap, then it becomes .1/.2/... and
    every later append goes to the highest part, so a shard never silently becomes
    a monolith again.
    """
    month = (date or today())[:7]
    if not re.match(r"^\d{4}-\d{2}$", month):
        month = today()[:7]
    base = LOG / kind
    cands = sorted(base.glob(f"{month}*.md"), key=_part_num)
    if not cands:
        return base / f"{month}.md"
    last = cands[-1]
    if last.stat().st_size > 200_000:
        if _part_num(last) > 1:
            return base / f"{month}.{_part_num(last) + 1}.md"
        new = base / f"{month}.1.md"
        if not new.exists():
            last.rename(new)          # first split: the plain month becomes .1
        return base / f"{month}.2.md"
    return last


def append_block(path: Path, header: str, block: str) -> None:
    """Append to a shard, guaranteeing the file ends with a newline first.

    A shard whose last line lacked a trailing newline produced
    `---<!-- e:pain|P56|... -->` — a marker that no longer starts its line, so the
    parser silently folded one entry into the previous one's body. Writers go
    through here so that cannot happen again.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    need_nl = False
    if path.exists() and path.stat().st_size:
        with path.open("rb") as fh:
            fh.seek(-1, os.SEEK_END)
            need_nl = fh.read(1) != b"\n"
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        if need_nl:
            fh.write("\n")
        fh.write(header + block)


def cmd_append(args) -> int:
    kind = args.kind
    if kind not in KINDS:
        print(f"unknown kind {kind}", file=sys.stderr)
        return 2
    body = Path(args.body).read_text(encoding="utf-8") if args.body and args.body != "-" else sys.stdin.read()
    if not body.strip():
        print("empty body — refusing to write an empty entry", file=sys.stderr)
        return 2
    best, _ = remote_max(kind)
    id_full = f"{KINDS[kind]['letter']}{best + 1}"
    # a handoff entry is identified by its timestamp, so both the heading and the
    # marker carry one; anything else is a plain date.
    stamp = args.date or (now_utc() if kind == "handoff" else today())
    day = stamp[:10]
    heading = build_heading(kind, id_full, args.title, stamp, args.host or host_tag())
    path = shard_path(kind, day)
    path.parent.mkdir(parents=True, exist_ok=True)
    header = ""
    if not path.exists():
        header = (f"# {kind} · {path.stem}\n"
                  f"<!-- journal shard: append-only, oldest first. Never edit an entry — correct it with a new\n"
                  f"     entry that cites it. Reads: python tools/journal.py newest {kind} 3 -->\n\n")
    marker = f"<!-- e:{kind}|{id_full}|{stamp}|{args.host or host_tag()}|{args.status} -->"
    block = f"{marker}\n{heading}\n\n{norm_body(body)}\n\n---\n"
    append_block(path, header, block)
    cmd_index(argparse.Namespace())
    print(f"+ {id_full} -> {path.relative_to(JOURNAL)}")
    if not args.no_check:
        rc = cmd_check(argparse.Namespace())
        return rc
    return 0


# ---------------------------------------------------------------------------
# Audit and migrate
# ---------------------------------------------------------------------------

STRUCTURE_RE = re.compile(r"^(##\s|[A-Z]{0,2}[LPDW]\d+[a-z]?\s*·|\*\*[LPDW]{1,2}\d+)")


def content_key(heading: str, body: str) -> str:
    """Loss-proof identity for a migration.

    Bodies are preserved verbatim while headings are rewritten (ids get collision
    suffixes, titles get normalised), so completeness is proved on the body. A few
    old entries carried their whole content on the heading line; for those the
    heading is the content. Structural lines — section headings such as '## On
    evidence', and entry headings — are dropped from both sides, because the
    migration moves them out of the body and into the shard's own structure.
    """
    lines = [ln for ln in norm_body(body).split("\n") if not STRUCTURE_RE.match(ln.strip())]
    text = norm_body("\n".join(lines))
    if not text:
        text = re.sub(r"[ \t]+", " ", (heading or "").strip())
        text = re.sub(r"^\*\*", "", text)
        text = re.sub(r"^[A-Z]{0,2}(?=[LPDW]\d)", "", text)
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def fingerprint(heading: str, body: str) -> str:
    return entry_hash(heading, body)


def cmd_audit(args) -> int:
    """Report entries that exist in another copy of the journal but not here.

    Used to prove a merge lost nothing, and to catch a machine that has drifted.
    Compares body content, so a renamed or renumbered entry still counts as present.
    """
    local = {content_key(e["heading"], e["body"]) for e in load_shards()}
    if args.local:
        local |= {content_key(r["heading"], "") for r in load_index()}
    missing_total = 0
    for raw in args.files:
        path = Path(raw)
        kind = args.kind or path.stem.split(".")[0].lower()
        kind = {"handoffs": "handoff"}.get(kind, kind)
        if kind not in KINDS:
            print(f"?? cannot tell the kind of {path} — pass --kind")
            continue
        ents = parse_legacy(path, kind)
        missing = [e for e in ents if content_key(e["heading"], e["body"]) not in local]
        missing_total += len(missing)
        print(f"{path.name}: {len(ents)} entries, {len(missing)} not present locally")
        for e in missing[:40]:
            print(f"   MISSING {e['id_full'] or '-':>6}  {e['heading'][:100]}")
    print(f"-- {missing_total} entry/entries missing locally")
    return 0 if missing_total == 0 else 1


def cmd_kinds(args) -> int:
    for k, v in KINDS.items():
        n = len([r for r in load_index() if r["kind"] == k])
        print(f"{k:<10} {v['letter']}  {n:>4} entries   log/{k}/YYYY-MM.md")
    return 0


# ---------------------------------------------------------------------------
# The state tier: small files that are always read, rewritten not appended
# ---------------------------------------------------------------------------

def field(body: str, name: str) -> str:
    """Pull a bold field ('**Cost.** ...') out of an entry body."""
    m = re.search(rf"(?im)^\*\*{name}\.?\*\*\s*(.*?)(?=\n\s*\n|\n\*\*|\Z)", body, re.S)
    if not m:
        return ""
    return re.sub(r"\s+", " ", m.group(1)).strip()


def cmd_state(args) -> int:
    rows = [r for r in load_index() if r["kind"] == "pain"]
    order = {k: i for i, k in enumerate(KINDS)}
    rows.sort(key=lambda r: (num_of(r["id_full"]), suffix_of(r["id_full"])))
    opens = [r for r in rows if r["status"] != "done"]
    out = [
        "# OPEN PAIN — what still hurts, ranked",
        "",
        f"Updated: {today()}",
        "",
        "**Generated** from `log/pain/` by `tools/journal.py state`. Do not edit by hand: an entry stops",
        "being open by being corrected, not by being deleted here. A problem that is done carries",
        "`status=done` in its marker and drops out of this list.",
        "",
        "| # | Symptom | Cost | Fix |",
        "|---|---|---|---|",
    ]
    for r in opens:
        body = read_lines(r["file"], int(r["line_start"]), int(r["line_end"]))
        cost = field(body, "Cost")[:200]
        fix = field(body, "Fix")[:200]
        title = re.sub(r"^##\s*", "", r["heading"])
        title = re.sub(r"^[A-Z]+\d+[a-z]?\s*[—–-]\s*", "", title)
        out.append(f"| {r['id_full']} | {title} | {cost} | {fix} |")
    path = STATE / "open-pain.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8", newline="\n")
    print(f"state/open-pain.md: {len(opens)} open of {len(rows)} ({len(rows) - len(opens)} done)")
    return 0


STATUS_LEDGER = STATE / "status.tsv"
STATUS_HEADER = "kind\tid\tstatus\tdate\thost\twhy"


def load_status_events() -> dict[tuple[str, str], tuple[str, str, str]]:
    """Append-only status corrections, last row per (kind, id) wins.

    The log is append-only, so 'this is fixed now' is a *new* fact about an old
    entry, not an edit to it. That is why status lives here and not in the shard.
    """
    out: dict[tuple[str, str], tuple[str, str, str]] = {}
    if not STATUS_LEDGER.exists():
        return out
    for ln in STATUS_LEDGER.read_text(encoding="utf-8", errors="replace").split("\n"):
        if not ln.strip() or ln.startswith("kind\t"):
            continue
        parts = (ln.split("\t") + ["", "", ""])[:6]
        kind, id_full, status, date, host, why = parts
        if kind and id_full:
            out[(kind, id_full)] = (status, date, why)
    return out


def effective_status(kind: str, id_full: str, marker_status: str, events=None) -> str:
    ev = (events if events is not None else load_status_events()).get((kind, id_full))
    return ev[0] if ev else (marker_status or "open")


def cmd_resolve(args) -> int:
    """Record that an entry's status changed. Appends; never edits the shard."""
    id_full = args.id.upper()
    rows = load_index()
    hit = [r for r in rows if r["id_full"].upper() == id_full]
    if not hit:
        print(f"no entry {args.id}", file=sys.stderr)
        return 2
    kind = hit[0]["kind"]
    line = "\t".join([kind, hit[0]["id_full"], args.status, today(), host_tag(), args.why or ""])
    if not STATUS_LEDGER.exists():
        STATUS_LEDGER.parent.mkdir(parents=True, exist_ok=True)
        STATUS_LEDGER.write_text(STATUS_HEADER + "\n", encoding="utf-8", newline="\n")
    with STATUS_LEDGER.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(line + "\n")
    cmd_index(argparse.Namespace())
    cmd_state(argparse.Namespace())
    print(f"= {hit[0]['id_full']} -> {args.status} ({args.why or 'no reason given'})")
    return 0


def _title_of(heading: str, kind: str) -> str:
    """Recover a bare title from a heading of any shape the old files grew."""
    h = heading.strip()
    if kind == "lessons":
        h = re.sub(r"^\*\*[A-Z]{0,2}L\d+\s*·\s*", "", h)
    elif kind == "pain":
        h = re.sub(r"^##\s*[A-Z]{0,2}P\d+\b", "", h).strip(" —–-")
    else:
        h = re.sub(r"^\*\*[A-Z]{0,2}[DW]\d+[a-z]?\s*·\s*", "", h)
        h = re.sub(r"^\d{4}-\d{2}-\d{2}[^·]*·\s*", "", h)
    h = h.strip().strip("*").strip()
    return h[:-1] if h.endswith(".") else (h or "(untitled)")


def cmd_import_flat(args) -> int:
    """Absorb new entries from the retired flat files into the shards.

    Built because two sessions were writing the flat journal at once on 2026-09-14:
    anything that lands in HANDOFF.md/LESSONS.md/... after the rebuild is imported
    here rather than lost. Idempotent — an entry already in a shard is skipped by
    content, so this can be run as often as needed until the flat files go quiet.

    It also handles the other direction the same session used: **a flat entry that
    grew after the migration**. If the stored body is a prefix of the incoming one,
    the entry is resynced in place rather than duplicated — appending a second copy
    of the same problem is how a journal stops being readable.
    """
    import argparse as _a
    targets = args.files or [
        str(JOURNAL / f"{name}.md") for name in
        ("HANDOFF", "LESSONS", "PAIN", "DECISIONS", "WINS")
    ]
    shard_entries = load_shards()
    local = {content_key(e["heading"], e["body"]) for e in shard_entries}
    total_new = total_resync = 0
    for raw in targets:
        path = Path(raw)
        if not path.exists():
            print(f"-- absent: {path.name}")
            continue
        kind = args.kind or path.stem.split(".")[0].lower()
        if kind not in KINDS:
            continue
        ents = parse_legacy(path, kind)
        if not ents:
            print(f"-- {path.name}: nothing parseable")
            continue
        new = [e for e in ents if content_key(e["heading"], e["body"]) not in local]
        resyncs = []
        for e in new:
            stored = [s for s in shard_entries
                      if s["kind"] == kind and e["id_full"] and s["id_full"] == e["id_full"]]
            for s in stored:
                if s["body"] and norm_body(e["body"]).startswith(norm_body(s["body"])):
                    resyncs.append((s, e))
                    break
        for s, e in resyncs:
            p = JOURNAL / s["file"]
            lines = p.read_text(encoding="utf-8", errors="replace").split("\n")
            head = lines[:s["heading_end"]]                      # through the heading line
            tail = lines[s["line_end"] - 1:]                     # separator and anything after
            p.write_text("\n".join(head + [norm_body(e["body"]), ""] + tail).lstrip("\n"),
                         encoding="utf-8", newline="\n")
            print(f"~ {s['id_full']} resynced from {path.name} (source grew by "
                  f"{len(norm_body(e['body'])) - len(norm_body(s['body']))} chars)")
            local.add(content_key(e["heading"], e["body"]))
            total_resync += 1
        resynced_ids = {s["id_full"] for s, _ in resyncs}
        new = [e for e in new if e["id_full"] not in resynced_ids]
        if not new:
            print(f"-- {path.name}: {len(ents)} entries, nothing new ({len(resyncs)} resynced)")
            continue
        base, _ = remote_max(kind)
        letter = KINDS[kind]["letter"]
        for e in new:
            base += 1
            id_full = f"{letter}{base}"
            date = e["date"] or today()
            heading = e["heading"] if kind == "handoff" else build_heading(
                kind, id_full, _title_of(e["heading"], kind), date, e["host"] or "imported")
            path_out = shard_path(kind, date)
            path_out.parent.mkdir(parents=True, exist_ok=True)
            header = ""
            if not path_out.exists():
                header = (f"# {kind} · {path_out.stem}\n"
                          "<!-- journal shard: append-only, oldest first. Never edit an entry — correct it\n"
                          f"     with an entry that cites it. Reads: python tools/journal.py newest {kind} 3 -->\n\n")
            status = "open"
            marker = f"<!-- e:{kind}|{id_full}|{date}|{e['host'] or 'imported'}|{status} -->"
            append_block(path_out, header, f"{marker}\n{heading}\n\n{norm_body(e['body'])}\n\n---\n")
            local.add(content_key(e["heading"], e["body"]))
            print(f"+ {id_full} <- {path.name}:{e['line_start']}  {heading[:80]}")
            total_new += 1
    if total_new:
        cmd_index(_a.Namespace())
        cmd_state(_a.Namespace())
    print(f"-- imported {total_new} new entry/entries")
    return 0


def cmd_split_shard(args) -> int:
    """Split an oversized shard at entry boundaries.

    A shard is never read whole (that is what the index is for), but it is read by
    `git diff`, by a careless future self, and by search; keeping a month under the
    cap is the cheap defence. Names become 2026-09.1.md, 2026-09.2.md.
    """
    path = JOURNAL / args.shard if not Path(args.shard).is_absolute() else Path(args.shard)
    kind = path.name.split(".")[0]
    month = path.stem
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.split("\n")
    starts = [i for i, ln in enumerate(lines) if MARKER_RE.match(ln)]
    if not starts:
        print("no entries in that shard", file=sys.stderr)
        return 2
    blocks: list[str] = []
    preamble = "\n".join(lines[:starts[0]]).rstrip()
    for n, i in enumerate(starts):
        end = starts[n + 1] if n + 1 < len(starts) else len(lines)
        blocks.append("\n".join(lines[i:end]).rstrip())
    cap = args.max_kb * 1024
    parts: list[list[str]] = [[]]
    size = len(preamble)
    for b in blocks:
        if size + len(b) > cap and parts[-1]:
            parts.append([])
            size = len(preamble)
        parts[-1].append(b)
        size += len(b) + 2
    if len(parts) == 1:
        print(f"{path.name}: {len(blocks)} entries, {len(text) // 1024} KB — already under {args.max_kb} KB")
        return 0
    path.unlink()
    for n, part in enumerate(parts, 1):
        out = path.with_name(f"{month}.{n}.md")
        body = "\n\n".join(part)
        head = re.sub(r"^#\s+.*$", f"# {kind} · {month}.{n}", preamble, count=1, flags=re.M)
        out.write_text(f"{head}\n\n{body}\n", encoding="utf-8", newline="\n")
        print(f"{out.name}: {len(part)} entries, {out.stat().st_size // 1024} KB")
    cmd_index(argparse.Namespace())
    return 0


def cmd_questions(args) -> int:
    """Mirror owner_decision_queue into the state tier.

    The database is authoritative; this file exists so a session that cannot reach
    the authority still knows what is already waiting on the owner, and so the same
    question is never asked twice in two different stores.
    """
    raw = sys.stdin.read() if args.from_json in ("-", "") else Path(args.from_json).read_text(encoding="utf-8")
    import json
    try:
        rows = json.loads(raw)
    except Exception as exc:
        print(f"could not parse the queue dump: {exc}", file=sys.stderr)
        return 2
    pending = [r for r in rows if (r.get("status") or "") == "pending"]
    out = [
        "# OWNER QUESTIONS — open only",
        "",
        f"Updated: {today()}",
        "",
        "**Generated** from `owner_decision_queue` on the authority by `tools/journal.py questions`.",
        "That table is the single source of truth for what is waiting on the owner; this is a mirror,",
        "so a session with no route to the authority still reads the truth instead of re-asking.",
        "Do not add a question here: add it there.",
        f"Provenance: {len(rows)} row(s) read, {len(pending)} pending, generated {now_utc()} on {host_tag()}.",
        "",
        "| # | Asked | Sev | Question | My recommendation |",
        "|---|---|---|---|---|",
    ]
    for r in pending:
        q = re.sub(r"\s+", " ", (r.get("question") or ""))[:400]
        rec = re.sub(r"\s+", " ", (r.get("recommendation") or ""))[:220]
        out.append(f"| {r.get('id')} | {(r.get('asked_at') or '')[:10]} | {r.get('severity')} | {q} | {rec} |")
    closed = [r for r in rows if (r.get("status") or "") != "pending"]
    out += ["", f"Closed since the queue opened: {len(closed)}. "
                "Answered questions move to `log/decisions/` with the owner's own words."]
    path = STATE / "owner-questions.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8", newline="\n")
    print(f"state/owner-questions.md: {len(pending)} open, {len(closed)} closed")
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    p = argparse.ArgumentParser(prog="journal.py", description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("status", help="the always-read page (bounded)")
    s.set_defaults(func=cmd_status)
    s = sub.add_parser("newest", help="newest N entries of a kind")
    s.add_argument("kind")
    s.add_argument("n", type=int, nargs="?", default=1)
    s.set_defaults(func=cmd_newest)
    s = sub.add_parser("show", help="print one entry by id (P46, L173, D41, W25, H64)")
    s.add_argument("id")
    s.add_argument("--all", action="store_true")
    s.set_defaults(func=cmd_show)
    s = sub.add_parser("search", help="regex across the journal, never whole files")
    s.add_argument("pattern")
    s.add_argument("--limit", type=int, default=40)
    s.set_defaults(func=cmd_search)
    s = sub.add_parser("index", help="regenerate index/entries.tsv from the shards")
    s.set_defaults(func=cmd_index)
    s = sub.add_parser("check", help="integrity: duplicate ids, ambiguity, staleness")
    s.set_defaults(func=cmd_check)
    s = sub.add_parser("next-id", help="the next free number for a kind (over index, shards and git)")
    s.add_argument("kind")
    s.set_defaults(func=cmd_next_id)
    s = sub.add_parser("append", help="write an entry; the only sanctioned way")
    s.add_argument("kind")
    s.add_argument("--title", required=True)
    s.add_argument("--date", default="")
    s.add_argument("--host", default="")
    s.add_argument("--status", default="open")
    s.add_argument("--body", default="-")
    s.add_argument("--no-check", action="store_true")
    s.set_defaults(func=cmd_append)
    s = sub.add_parser("audit", help="entries present in another copy but not here")
    s.add_argument("files", nargs="+")
    s.add_argument("--kind", default="")
    s.add_argument("--local", action="store_true", help="also trust index headings for empty-bodied entries")
    s.set_defaults(func=cmd_audit)
    s = sub.add_parser("kinds", help="what lives where")
    s.set_defaults(func=cmd_kinds)
    s = sub.add_parser("state", help="regenerate state/open-pain.md from the log")
    s.set_defaults(func=cmd_state)
    s = sub.add_parser("questions", help="mirror owner_decision_queue into state/owner-questions.md")
    s.add_argument("--from-json", default="-", help="JSON dump from `owner-queue.py list --all --json`")
    s.set_defaults(func=cmd_questions)
    s = sub.add_parser("split-shard", help="split an oversized shard at entry boundaries")
    s.add_argument("shard", help="path relative to the journal, e.g. log/handoff/2026-09.md")
    s.add_argument("--max-kb", type=int, default=200)
    s.set_defaults(func=cmd_split_shard)
    s = sub.add_parser("import-flat", help="absorb entries that landed in the retired flat files")
    s.add_argument("files", nargs="*")
    s.add_argument("--kind", default="")
    s.set_defaults(func=cmd_import_flat)
    s = sub.add_parser("resolve", help="record that an entry's status changed (append-only)")
    s.add_argument("id")
    s.add_argument("--status", default="done",
                   choices=["open", "done", "retracted", "superseded", "blocked"])
    s.add_argument("--why", default="")
    s.set_defaults(func=cmd_resolve)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
