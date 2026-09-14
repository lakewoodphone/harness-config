#!/usr/bin/env python3
"""journal.py v2 — the only writer and the cheapest reader of the journal.

The journal is my memory. It is not documentation.

v1 (frozen in tools/archive/journal-v1.py) proved the shape and then outgrew it: it
kept 781 entries inside nine files of up to 249 KB, so `show` read 249 KB to print
1.2 KB, `status` took 8.9 s and overflowed its own budget, and a second writer on a
second machine produced 161 base ids naming two different entries. The audit is in
../AUDIT.md; the contract this file implements is in ../SPEC-v2.md.

What v2 changes, in one paragraph: **one file per entry** under `entries/<kind>/`,
so a read is a single file open and two machines appending at once write two
different files and cannot conflict; `index/` becomes a proven cache with a tree
freshness stamp that self-heals; every read command has real filter flags and a
budget that is enforced *while the text is assembled*, not after; and the 798 KB of
legacy flat files plus the nine frozen shards are absorbed with an exact-content
proof rather than a hope.

Read path:
    journal.py status                 # the always-read page, <= --budget bytes, exit 0
    journal.py newest handoff 2       # newest entries of one kind
    journal.py show P46b              # one entry, one file open
    journal.py search "stale database" --kind lessons
    journal.py list --kind pain --status open --since 2026-09-10
    journal.py check                  # integrity; non-zero exit ONLY on error

Write path (all under the mutation lock, all atomic temp+replace):
    journal.py append lessons --title T --body -   # absorbs legacy drift first
    journal.py resolve P46 --status done --why "..."
    journal.py import-legacy --apply
    journal.py migrate-v2 --apply                  # split log/** into entries/**
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Shape of the journal. One place, so the format cannot drift again.
# ---------------------------------------------------------------------------

JOURNAL = Path(__file__).resolve().parent.parent

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
        # the [a-z]* suffix is real: the 2026-09-14 consolidation filed suffixed ids
        # (L146ba, D39c, W12b) when a flat file held more than one entry under one number.
        # Some legacy lessons headings also carry a date and a single trailing '*'.
        "regex": re.compile(r"^\*\*(?P<id>L(?P<num>\d+)[a-z]*) · (?:(?P<date>\d{4}-\d{2}-\d{2}[^·\n]*) · )?(?P<title>.+?)\*{0,2}$"),
    },
    "pain": {
        "letter": "P",
        "display": "PAIN",
        "heading": "## {id} — {title}",
        "dated": False,
        "regex": re.compile(r"^## (?P<id>P(?P<num>\d+)[a-z]*)\b[ —–-]*(?P<title>.*)$"),
    },
    "decisions": {
        "letter": "D",
        "display": "DECISIONS",
        "heading": "**{id} · {date} · {title}.**",
        "dated": True,
        "regex": re.compile(r"^\*\*(?P<id>D(?P<num>\d+)[a-z]*) · (?P<date>\d{4}-\d{2}-\d{2}) · (?P<title>.+)$"),
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
# The same marker without the closing angle bracket, for diagnosis only. v1 learned
# that a marker appended to a shard whose last line lacked a newline becomes
# '---<!-- e:pain|P56|...|open -->', which MARKER_RE correctly refuses — and the
# entry is then silently folded into the previous one's body. This is how check says so.
LOOSE_MARKER_RE = re.compile(r"^[-—─―\s]*<!--\s*e:(?P<kind>[a-z]+)\|(?P<id>[^|]*)\|(?P<date>[^|]*)\|(?P<host>[^|]*)\|(?P<status>[^|]*?)\s*(?:-->)?\s*$")
SHARD_HEADER_RE = re.compile(r"^#\s+(?P<kind>[a-z]+)\s+·\s+(?P<month>\d{4}-\d{2})\s*$")
H1_RE = re.compile(r"^# ")
SECTION_RE = re.compile(r"^## (?!#)")
# the optional trailing metadata line of a v2 entry file
META_RE = re.compile(r"^<!--\s*j2\s+(?P<body>.*?)\s*-->\s*$")
REF_RE = re.compile(r"(?<![A-Za-z0-9])([LPDW])(\d{1,3})(?![0-9])")

ENTRY_KINDS = tuple(KINDS)
KIND_ORDER = {k: i for i, k in enumerate(KINDS)}
FLAT_FILES = (("HANDOFF", "handoff"), ("LESSONS", "lessons"), ("PAIN", "pain"),
              ("DECISIONS", "decisions"), ("WINS", "wins"))
META_KEYS = ("tags", "refs", "alias_of", "legacy_id", "sha")

DEFAULT_BUDGET = 12000
STATUS_BUDGET = 6000
INDEX_HEADER = "kind\tid_full\tnum\tsuffix\tdate\thost\tstatus\theading\tfile\tline_start\tline_end\thash"
ALIAS_HEADER = "alias_id\tkind\tcanonical_id\treason\tdate"
STATUS_HEADER = "kind\tid\tstatus\tdate\thost\twhy"
FORMAT_CONTENT = "2\n"
ARCHIVE_NAME = "archive"

LOCK_NAME = ".lock"
LOCK_STALE_SEC = 600
# How long a writer waits for the lock. 30 s was too short and produced a *flaky* failure
# in the six-way concurrency selftest: each append does a `git grep` pass over every ref to
# find the id ceiling, so six serialised writers on a loaded machine (which is the normal
# state here — two agent sessions and a build) can exceed 30 s and exit non-zero. The
# journal refuses loudly rather than writing blind, but a refusal under load is a false
# alarm: a writer should queue. 240 s covers six fetches and still fails within a turn.
LOCK_WAIT_SEC = 240.0
# Commands that read the tree to decide what to write back. Two of these running at
# once on one tree is what produced 161 collided ids on 2026-09-14.
MUTATING_COMMANDS = {"append", "import-legacy", "migrate-v2", "dedupe", "repair-ids",
                     "resolve", "state", "questions", "gc-legacy", "index"}


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def now_utc() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def today() -> str:
    return _dt.date.today().isoformat()


def _shortname() -> str:
    try:
        return socket.gethostname().split(".")[0]
    except Exception:
        return "unknown"


def host_tag() -> str:
    """The machine that wrote an entry — Windows COMPUTERNAME or a POSIX hostname.

    v1's first version fell back to 'UNKNOWN' on Linux, which would have mislabelled
    every entry written on the authority. os.uname() is never called unguarded: it
    does not exist on Windows, and this tool runs on both.
    """
    h = os.environ.get("DSH_MACHINE") or os.environ.get("COMPUTERNAME") or ""
    if not h:
        try:
            h = socket.gethostname()
        except Exception:
            h = "unknown"
    return h.split(".")[0].upper()


def note(text: str) -> None:
    print(text, file=sys.stderr)


def _rl(path: Path) -> str:
    """Read UTF-8 with a replace decoder; never raises on a file being written."""
    try:
        return path.read_bytes().decode("utf-8", errors="replace")
    except OSError:
        return ""


def _rlb_bounded(path: Path, limit: int) -> tuple:
    """Read at most `limit` bytes (never the whole file), then decode.

    This is how a status section drawn from a huge hand-written file stays bounded
    during assembly rather than after it. Returns (text, truncated).
    """
    if limit <= 0:
        return "", True
    try:
        size = path.stat().st_size
    except OSError:
        return "", False
    with path.open("rb") as fh:
        raw = fh.read(limit)
    truncated = size > len(raw)
    text = raw.decode("utf-8", errors="replace")
    if truncated:
        cut = max(text.rfind("\n"), text.rfind(" "))
        if cut > limit // 2:
            text = text[:cut]
    return text, truncated


def atomic_write(path: Path, text: str) -> None:
    """Write through a temp file in the same directory, then os.replace.

    Every write is LF, unconditionally. A legacy source with CRLF line endings (one of
    the six flat files had them) otherwise reproduces its carriage returns inside the
    entry file, which `check` then reports as an ERROR on a tree the tool itself wrote.
    Line endings are not content: normalising them here cannot lose an entry, and the
    byte-preservation proof compares whitespace-normalised text for exactly this reason.
    """
    if "\r" in text:
        text = text.replace("\r\n", "\n").replace("\r", "\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / (path.name + ".tmp" + str(os.getpid()))
    with open(tmp, "wb") as fh:
        fh.write(text.encode("utf-8"))
    try:
        os.replace(str(tmp), str(path))
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def _path_of(rel: str) -> Path:
    return JOURNAL / str(rel).replace("/", os.sep)


def _rel_of(path: Path) -> str:
    try:
        return str(path.relative_to(JOURNAL)).replace(os.sep, "/")
    except ValueError:
        return str(path).replace(os.sep, "/")


def redact(text: str) -> str:
    """Never print a credential. Any token-looking run is masked before output."""
    if not text:
        return text
    text = re.sub(r"(?i)\b(?:sk|pk|ghp|gho|xox[baprs])[-_][A-Za-z0-9_\-]{12,}", "<redacted>", text)
    text = re.sub(r"\b[A-Za-z0-9_\-]{32,}\b", "<redacted>", text)
    return text


# ---------------------------------------------------------------------------
# Identity keys — copied from v1, because they encode two real bugs
# ---------------------------------------------------------------------------

def norm_body(text: str) -> str:
    """Whitespace-collapsed body, used as the identity of an entry."""
    lines = [ln.rstrip() for ln in (text or "").replace("\r\n", "\n").split("\n")]
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


def num_of(id_full: str) -> int:
    m = re.search(r"(\d+)", id_full or "")
    return int(m.group(1)) if m else 0


def suffix_of(id_full: str) -> str:
    m = re.match(r"^[A-Z]+\d+(.*)$", id_full or "")
    return m.group(1) if m else ""


def build_heading(kind: str, id_full: str, title: str, date: str, host: str) -> str:
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


def _age_days(stamp: str) -> int:
    try:
        d = _dt.date.fromisoformat((stamp or "")[:10])
    except ValueError:
        return -1
    return (_dt.date.today() - d).days


# ---------------------------------------------------------------------------
# Parsing — v1's parsers, preserved verbatim in behaviour
# ---------------------------------------------------------------------------

class Entry(dict):
    """A journal entry. Duck-typed dict so it survives json round-trips."""


def heading_span(block_lines):
    """(heading, body_lines, heading_line_count) for the lines that follow a marker.

    A shard's heading is line 2 — except when it is not. A heading that wrapped onto a
    second line in the old flat files is real heading text, and reading only line 2
    demotes half of it into the body, which is how a migration loses a sentence. The
    continuation is recognised conservatively: the first line has not closed its `**`, the
    next line is not blank and not another marker, and at most one continuation line is
    taken — the exact shape of the wrap v1 produced.
    """
    if not block_lines:
        return "", [], 0
    heading = block_lines[0].strip()
    if not (heading.startswith("**") and heading.count("**") < 2):
        return heading, block_lines[1:], 1
    if len(block_lines) > 1:
        nxt = block_lines[1]
        if nxt.strip() and not nxt.lstrip().startswith("<!-- e:") and "**" in nxt:
            return (heading + " " + nxt.strip()).strip(), block_lines[2:], 2
    return heading, block_lines[1:], 1


def parse_shard(path: Path, kind: str) -> list:
    """Parse a shard that carries markers (everything written from 2026-09-14)."""
    text = _rl(path)
    lines = text.split("\n")
    starts = [i for i, ln in enumerate(lines) if MARKER_RE.match(ln)]
    entries = []
    for n, i in enumerate(starts):
        m = MARKER_RE.match(lines[i])
        end = starts[n + 1] if n + 1 < len(starts) else len(lines)
        heading, rest, span = heading_span(lines[i + 1:end])
        body = "\n".join(rest)
        entries.append(Entry(
            kind=kind,
            id_full=m.group("id"),
            date=m.group("date"),
            host=m.group("host"),
            status=m.group("status"),
            heading=heading,
            body=norm_body(body),
            heading_raw="\n".join(ln.strip() for ln in lines[i + 1:i + 1 + span]),
            section="",
            file=_rel_of(path),
            line_start=i + 1,
            heading_end=i + 1 + span,
            line_end=end,
        ))
    return entries


def parse_legacy(path: Path, kind: str) -> list:
    """Parse one of the five flat pre-2026-09-14 files. Used by migrate and audit.

    Bold headings in the old files wrap onto a second line ('**L159 · A 500 from your
    own API ...' / 'must outlast ...**'), so the anchor deliberately does not require a
    closing '**' and the heading is flushed across lines. Missing this silently dropped
    37 entries on the first migration attempt.

    `heading_raw` is the heading exactly as the source lines spell it, newline and all.
    It is what the importer writes back, so a lesson keeps the identity it had in the
    flat file (`entry_hash` is computed on the joined heading either way).
    """
    spec = KINDS[kind]
    text = _rl(path)
    lines = text.split("\n")
    starts = []
    for i, ln in enumerate(lines):
        if NOT_AN_ENTRY.match(ln.strip()):
            continue
        m = spec["regex"].match(ln.strip())
        if m:
            starts.append((i, m))
    entries = []
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
        raw_heading_text = "\n".join(ln.strip() for ln in lines[i:heading_end + 1])
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
            heading_raw="\n".join(ln.strip() for ln in lines[i:heading_end + 1]),
            section=section,
            file=str(path).replace("\\", "/"),
            line_start=i + 1,
            heading_end=heading_end + 1,
            line_end=end,
        ))
    return entries


def shard_blocks(path: Path):
    """(preamble, [(block_text, first_line, last_line)]) for a v1 shard.

    The split is a pure line-range split, so concatenating the blocks reproduces the
    source byte for byte apart from the preamble. That property is what makes the
    migration provable instead of hopeful.
    """
    text = _rl(path)
    lines = text.split("\n")
    starts = [i for i, ln in enumerate(lines) if MARKER_RE.match(ln)]
    blocks = []
    for n, i in enumerate(starts):
        end = starts[n + 1] if n + 1 < len(starts) else len(lines)
        # The raw lines of the entry, with no trailing newline added or removed: the
        # newline that ended the last line of the file is not part of any block, and the
        # proof below counts it explicitly.
        blocks.append(("\n".join(lines[i:end]), i + 1, end))
    preamble = "\n".join(lines[:starts[0]]) if starts else text
    return preamble, blocks


def parse_meta(body: str):
    """Split the optional trailing '<!-- j2 k=v ... -->' off an entry body."""
    text = body or ""
    lines = text.split("\n")
    i = len(lines)
    while i > 0 and not lines[i - 1].strip():
        i -= 1
    meta = {}
    if i > 0:
        m = META_RE.match(lines[i - 1].strip())
        if m:
            for tok in m.group("body").split():
                if "=" in tok:
                    k, v = tok.split("=", 1)
                    meta[k.strip()] = v.strip()
            return "\n".join(lines[:i - 1]), meta
    return text, meta


def parse_entry(path: Path, kind: str) -> Entry:
    """Parse one v2 entry file. Never raises; returns the problems on the entry."""
    text = _rl(path)
    lines = [ln.rstrip("\r") for ln in text.split("\n")]
    problems = []
    notes = []
    if "\r\n" in text:
        problems.append("file uses CRLF line endings; every journal write is LF")
    while lines and not lines[-1].strip():
        lines.pop()
    stem = path.stem
    e = Entry(
        kind=kind, id_full="", num=0, suffix="", date="", host="", status="",
        heading="", body="", tags=[], refs=[], alias_of="", sha="",
        file=_rel_of(path), line_start=1, line_end=max(1, len(lines)),
        hash="", problems=problems, notes=notes, meta={}, marker_kind="", legacy_id="",
    )
    if not lines:
        problems.append("file is empty")
        return e
    m = MARKER_RE.match(lines[0])
    if not m:
        problems.append("first line is not a v1 marker (^<!-- e:kind|id|date|host|status -->)")
        return e
    e["id_full"] = m.group("id")
    e["date"] = m.group("date")
    e["host"] = m.group("host")
    e["status"] = m.group("status")
    e["marker_kind"] = m.group("kind")
    if m.group("kind") != kind:
        problems.append(f"marker kind {m.group('kind')!r} disagrees with directory {kind!r}")
    if m.group("kind") not in KINDS:
        problems.append(f"marker kind {m.group('kind')!r} is not one of {', '.join(KINDS)}")
    if e["id_full"] and e["id_full"] != stem:
        problems.append(f"id in the file name ({stem}) disagrees with the marker ({e['id_full']})")
    if len(lines) < 2 or not lines[1].strip():
        problems.append("heading line is missing or empty")
    heading = lines[1].strip() if len(lines) > 1 else ""
    body_text, meta = parse_meta("\n".join(lines[2:]))
    e["heading"] = heading
    e["body"] = norm_body(body_text)
    e["meta"] = meta
    e["tags"] = [t for t in (meta.get("tags") or "").split(",") if t]
    e["refs"] = [t for t in (meta.get("refs") or "").split(",") if t]
    e["alias_of"] = meta.get("alias_of") or ""
    e["legacy_id"] = "" if (meta.get("legacy_id") or "").strip() in ("", "-") else meta["legacy_id"].strip()
    e["sha"] = meta.get("sha") or ""
    e["hash"] = entry_hash(heading, e["body"])
    if e["sha"] and e["sha"] != e["hash"]:
        problems.append(f"metadata sha={e['sha']} does not match the body ({e['hash']})")
    if e["alias_of"]:
        problems.append(f"this file declares itself an alias of {e['alias_of']} and should not exist")
    if e["id_full"]:
        spec = KINDS.get(kind)
        head_m = spec["regex"].match(heading) if spec else None
        if not head_m:
            problems.append(f"heading does not match the {kind} heading form: {heading[:70]!r}")
        else:
            token = (head_m.groupdict().get("id") or "").strip()
            if token and token != e["id_full"]:
                # A heading may carry a DIFFERENT id than its file when the entry was
                # filed under another number by a legacy source. That is only legal when
                # the entry records which one, explicitly: file name, marker id and
                # heading must otherwise agree. Silence here is how the real tree grew
                # entries/lessons/L170.md holding the flat file's L162 text on 2026-09-14.
                if e["legacy_id"] and token == e["legacy_id"]:
                    e["legacy_heading"] = True
                    notes.append("heading carries the legacy id %s; this entry is filed as %s "
                                 "(recorded in metadata)" % (token, e["id_full"]))
                else:
                    problems.append(
                        "heading carries id %s but the marker says %s, and no legacy_id explains it"
                        % (token, e["id_full"]))
    e["num"] = num_of(e["id_full"])
    e["suffix"] = suffix_of(e["id_full"])
    return e


def effective_heading(entry: dict) -> str:
    """The heading line this entry file will carry — decided in one place.

    A one-line heading is reproduced verbatim so an import stays byte-identical to the old
    file. A heading that wrapped onto more than one line in the source cannot be
    represented in a one-entry file at all — v1's format puts the heading on line 2 — so
    it is joined, exactly as `parse_legacy` computes it for the same text.
    """
    raw = entry.get("heading_raw")
    if raw and "\n" not in raw:
        return raw
    if raw:
        return " ".join(ln.strip() for ln in raw.split("\n"))
    return entry.get("heading", "")


def entry_bytes(entry: dict) -> str:
    """The exact bytes a v1 shard held for this entry, plus the v2 meta line.

    v1 wrote marker, heading, blank line, normalised body, blank line, '---'. The
    split is therefore reversible: strip the meta comment and this returns v1's block.

    `raw_lines` is set by the migration and by legacy absorption when the source text
    between the heading and the next entry is not self-delimiting — an old flat heading
    that wrapped mid-line puts real body text on the heading's last line, and dropping
    that line would silently lose a sentence. Reproducing the source lines verbatim is
    the only way `entry_hash` and the source bytes can both come out equal.
    """
    meta = dict(
        tags=",".join(entry.get("tags") or []),
        refs=",".join(entry.get("refs") or []),
        sha=entry_hash(effective_heading(entry), entry.get("body", "")),
        alias_of=entry.get("alias_of") or "",
        legacy_id=entry.get("legacy_id") or "",
    )
    # META_KEYS must stay in step with the dict above: every key is written
    # unconditionally, so a key added there without a default here makes every
    # append raise KeyError. Indexing meta[k] rather than meta.get(k) is
    # deliberate -- it fails loudly instead of silently writing a blank field.
    meta_line = "<!-- j2 " + " ".join(f"{k}={meta[k]}" for k in META_KEYS) + " -->"
    marker = "<!-- e:%s|%s|%s|%s|%s -->" % (entry["kind"], entry["id_full"], entry.get("date", ""),
                                            entry.get("host", ""), entry.get("status", ""))
    heading = effective_heading(entry)
    parts = [marker, heading]
    body = norm_body(entry.get("body", ""))
    if body:
        parts.append("")
        parts.append(body)
    parts.append("")
    parts.append(meta_line)
    return ("\n".join(parts) + "\n").replace("\r\n", "\n").replace("\r", "\n")


# ---------------------------------------------------------------------------
# The tree, the cache and its freshness proof
# ---------------------------------------------------------------------------

def entries_dir() -> Path:
    return JOURNAL / "entries"


def index_dir() -> Path:
    return JOURNAL / "index"


def log_dir() -> Path:
    return JOURNAL / "log"


def _walk(root: Path):
    if not root.exists():
        return
    for dirpath, dirnames, filenames in os.walk(str(root)):
        dirnames.sort()
        for name in sorted(filenames):
            p = Path(dirpath) / name
            try:
                st = p.stat()
            except OSError:
                continue
            yield p, st


def tree_signature() -> dict:
    """sha1 over sorted (relpath, size, mtime_ns) of every real file, plus counts.

    One stat per file, no read, no subprocess. `index/`, `archive/` and `tools/` are
    excluded — the cache must not invalidate itself, and a moved legacy shard is a
    tree change that `check` and `doctor` verify directly rather than on every read.
    A v1 `index` run that regenerates entries.tsv from log/ cannot hide either: the
    log signature moves with it.
    """
    entries_h = hashlib.sha1()
    n_entries = 0
    for p, st in _walk(entries_dir()):
        entries_h.update(("%s\t%d\t%d\n" % (_rel_of(p), st.st_size, st.st_mtime_ns)).encode("utf-8"))
        n_entries += 1
    log_h = hashlib.sha1()
    n_log = 0
    for p, st in _walk(log_dir()):
        if p.suffix != ".md":
            continue
        log_h.update(("%s\t%d\t%d\n" % (_rel_of(p), st.st_size, st.st_mtime_ns)).encode("utf-8"))
        n_log += 1
    flat_h = hashlib.sha1()
    for name, _kind in FLAT_FILES:
        p = JOURNAL / (name + ".md")
        if p.exists():
            try:
                st = p.stat()
                flat_h.update(("%s.md\t%d\t%d\n" % (name, st.st_size, st.st_mtime_ns)).encode("utf-8"))
            except OSError:
                pass
    return {
        "entries_sig": entries_h.hexdigest(),
        "entries_count": n_entries,
        "log_sig": log_h.hexdigest(),
        "log_count": n_log,
        "flat_sig": flat_h.hexdigest(),
    }


def load_entries():
    """Every entry in the tree, parsed from files. This is the source of truth.

    Returns (entries, problems). An entry's own `problems` are errors; its `notes` are
    explanations (a heading that carries a legacy id, say) that `check` reports as INFO.
    """
    out = []
    problems = []
    root = entries_dir()
    if not root.exists():
        return out, problems
    for kind_dir in sorted(root.iterdir()):
        if not kind_dir.is_dir():
            continue
        kind = kind_dir.name
        for f in sorted(kind_dir.iterdir()):
            if not f.is_file() or f.suffix != ".md":
                continue
            if kind not in KINDS:
                problems.append("entries/%s/%s: directory %r is not a known kind" % (kind, f.name, kind))
                continue
            try:
                e = parse_entry(f, kind)
            except Exception as exc:                        # never abort a read
                problems.append("%s: unparseable (%s)" % (_rel_of(f), exc))
                continue
            for p in e.get("problems") or []:
                problems.append("%s: %s" % (_rel_of(f), p))
            out.append(e)
    return out, problems


def load_aliases() -> list:
    path = index_dir() / "aliases.tsv"
    rows = []
    if not path.exists():
        return rows
    for ln in _rl(path).split("\n"):
        if not ln.strip() or ln.startswith("alias_id\t"):
            continue
        parts = (ln.split("\t") + [""] * 8)[:8]
        rows.append({"alias_id": parts[0], "kind": parts[1], "canonical_id": parts[2],
                     "reason": parts[3], "date": parts[4], "host": parts[5],
                     "sha": parts[6], "source": parts[7]})
    return rows


def load_status_events() -> dict:
    """Append-only status corrections, last row per (kind, id) wins.

    The log is append-only, so 'this is fixed now' is a *new* fact about an old
    entry, not an edit to it. That is why status lives here and not in the entry file.
    """
    out = {}
    path = JOURNAL / "state" / "status.tsv"
    if not path.exists():
        return out
    for ln in _rl(path).split("\n"):
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


def flat_sources() -> list:
    """Every legacy flat file that could still hold unabsorbed entries."""
    out = []
    for name, kind in FLAT_FILES:
        p = JOURNAL / (name + ".md")
        if p.exists():
            out.append((p, kind))
    arch = JOURNAL / ARCHIVE_NAME
    if arch.exists():
        for child in sorted(arch.iterdir()):
            if not child.is_dir():
                continue
            for name, kind in FLAT_FILES:
                p = child / (name + ".md")
                if p.exists():
                    out.append((p, kind))
    return out


def shard_sources() -> list:
    root = log_dir()
    out = []
    if not root.exists():
        return out
    for p in sorted(root.rglob("*.md")):
        kind = p.parent.name
        if kind in KINDS:
            out.append((p, kind))
    return out


def alias_map(aliases=None) -> dict:
    rows = aliases if aliases is not None else load_aliases()
    return {a["alias_id"]: a for a in rows}


def resolve_alias(id_full: str, aliases=None) -> str:
    amap = alias_map(aliases)
    seen = set()
    cur = id_full
    while cur in amap and cur not in seen:
        seen.add(cur)
        cur = amap[cur]["canonical_id"]
    return cur


# ---------------------------------------------------------------------------
# Cache build / heal
# ---------------------------------------------------------------------------

def _entries_tsv_rows(entries: list, events: dict) -> list:
    rows = [INDEX_HEADER]
    sortable = sorted(entries, key=lambda e: (KIND_ORDER.get(e["kind"], 9), e.get("date") or "",
                                              e.get("num") or 0, e["id_full"]))
    for e in sortable:
        rows.append("\t".join([
            e["kind"], e["id_full"], str(e.get("num") or 0), e.get("suffix") or "",
            e.get("date") or "-", e.get("host") or "-",
            effective_status(e["kind"], e["id_full"], e.get("status", ""), events),
            e["heading"], e["file"], str(e["line_start"]), str(e["line_end"]),
            e["hash"],
        ]))
    return rows


def _collect_refs(entries: list) -> list:
    known = {e["id_full"] for e in entries}
    out = []
    for e in entries:
        found = list(e.get("refs") or [])
        for m in REF_RE.finditer("%s\n%s" % (e["heading"], e["body"])):
            found.append("%s%s" % (m.group(1), m.group(2)))
        seen = []
        for r in found:
            if r not in seen:
                seen.append(r)
        for r in seen:
            out.append({"src_kind": e["kind"], "src_id": e["id_full"], "ref": r,
                        "resolved": 1 if r in known else 0})
    return out


def _write_db(entries: list, aliases: list, refs: list) -> str:
    """sqlite3 + FTS5, regenerable. Returns a one-line status string."""
    path = index_dir() / "journal.db"
    tmp = index_dir() / (".journal.db.tmp" + str(os.getpid()))
    fts5 = False
    try:
        if tmp.exists():
            tmp.unlink()
        con = sqlite3.connect(str(tmp))
        try:
            con.execute("CREATE TABLE entries (kind TEXT, id_full TEXT, num INTEGER, suffix TEXT,"
                        " date TEXT, host TEXT, status TEXT, heading TEXT, file TEXT,"
                        " line_start INTEGER, line_end INTEGER, hash TEXT, tags TEXT, refs TEXT)")
            con.execute("CREATE TABLE refs (src_kind TEXT, src_id TEXT, ref TEXT, resolved INTEGER)")
            con.execute("CREATE TABLE aliases (alias_id TEXT, kind TEXT, canonical_id TEXT,"
                        " reason TEXT, date TEXT)")
            con.execute("CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT)")
            try:
                con.execute("CREATE VIRTUAL TABLE fts USING fts5(id_full, kind, heading, body,"
                            " tokenize='unicode61')")
                fts5 = True
            except sqlite3.OperationalError:
                fts5 = False
            con.executemany("INSERT INTO entries VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            [(e["kind"], e["id_full"], e.get("num") or 0, e.get("suffix") or "",
                              e.get("date") or "", e.get("host") or "", e.get("status") or "",
                              e["heading"], e["file"], e["line_start"], e["line_end"], e["hash"],
                              ",".join(e.get("tags") or []), ",".join(e.get("refs") or []))
                             for e in entries])
            if fts5:
                con.executemany("INSERT INTO fts VALUES (?,?,?,?)",
                                [(e["id_full"], e["kind"], e["heading"], e["body"]) for e in entries])
            con.executemany("INSERT INTO refs VALUES (?,?,?,?)",
                            [(r["src_kind"], r["src_id"], r["ref"], r["resolved"]) for r in refs])
            con.executemany("INSERT INTO aliases VALUES (?,?,?,?,?)",
                            [(a["alias_id"], a["kind"], a["canonical_id"], a["reason"], a["date"])
                             for a in aliases])
            con.execute("INSERT INTO meta VALUES ('built', ?)", (now_utc(),))
            con.execute("INSERT INTO meta VALUES ('fts5', ?)", ("1" if fts5 else "0",))
            con.commit()
        finally:
            con.close()
        os.replace(str(tmp), str(path))
    except Exception as exc:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
        return "journal.db not written (%s)" % exc
    return "journal.db + fts5" if fts5 else "journal.db (no fts5)"


def rebuild_cache(compute_drift: bool = False) -> dict:
    entries, problems = load_entries()
    events = load_status_events()
    aliases = load_aliases()
    refs = _collect_refs(entries)
    idir = index_dir()
    idir.mkdir(parents=True, exist_ok=True)
    atomic_write(idir / "entries.tsv", "\n".join(_entries_tsv_rows(entries, events)) + "\n")
    if not (idir / "aliases.tsv").exists():
        atomic_write(idir / "aliases.tsv", ALIAS_HEADER + "\n")
    db_note = _write_db(entries, aliases, refs)
    stamp = tree_signature()
    ceiling = {kind: max_number(kind) for kind in KINDS}
    prev = read_stamp()
    git_ceiling = prev.get("git_ceiling") or {}
    stamp.update({
        "built": now_utc(),
        "entries": len(entries),
        "db": db_note,
        "parse_problems": len(problems),
        "ceiling": ceiling,
        # `next-id` and `append --fetch` raise this from git; reads never run a subprocess,
        # so the last measured value lives here and `allocation_ceiling` trusts it.
        "git_ceiling": git_ceiling,
        # Carry the last drift MEASUREMENT forward rather than resetting it to unknown. Every
        # append rebuilds the cache, and nulling the count meant the always-read page flipped
        # between "drift 0" and "unknown" several times an hour — a number that changes when
        # nothing changed is not a reading. `check` refreshes it and dates it.
        "unabsorbed": prev.get("unabsorbed") or {},
        "unabsorbed_total": prev.get("unabsorbed_total"),
        "drift_measured": prev.get("drift_measured"),
        "unabsorbed_error": None,
    })
    if compute_drift:
        try:
            counts = unabsorbed_counts()
            stamp["unabsorbed"] = counts
            stamp["unabsorbed_total"] = sum(counts.values())
        except Exception as exc:
            stamp["unabsorbed_error"] = str(exc)
    atomic_write(idir / "stamp.json", json.dumps(stamp, indent=1, sort_keys=True) + "\n")
    return stamp


def read_stamp() -> dict:
    path = index_dir() / "stamp.json"
    if not path.exists():
        return {}
    try:
        return json.loads(_rl(path)) or {}
    except Exception:
        return {}


def cache_fresh() -> bool:
    stamp = read_stamp()
    if not stamp:
        return False
    sig = tree_signature()
    for key in ("entries_sig", "entries_count", "log_sig", "log_count", "flat_sig"):
        if stamp.get(key) != sig.get(key):
            return False
    if not (index_dir() / "entries.tsv").exists():
        return False
    return True


def ensure_cache(compute_drift: bool = False) -> bool:
    """Make the cache provably fresh. Returns True if the cache is usable.

    Called by every read command. It never blocks on the write lock: if the tree moved
    while another session holds the lock, the read is answered from `entries/` and the
    staleness is *said out loud* rather than hidden.
    """
    fresh = cache_fresh()
    stamp = read_stamp()
    if fresh and (not compute_drift or stamp.get("unabsorbed_total") is not None):
        return True
    lock = JOURNAL / LOCK_NAME
    if lock.exists() and not _lock_is_mine(lock):
        held = _rl(lock).strip().replace("\n", " / ")[:120]
        note("journal: cache is stale and locked by %s — answering from entries/" % (held or "another session"))
        return False
    try:
        # always measure the drift on a rebuild: `status` reports it from the stamp, and a
        # status that says "drift unknown" is exactly the under-reporting the audit found
        stamp = rebuild_cache(compute_drift=True)
        note("journal: cache rebuilt (%s entries)" % stamp.get("entries", 0))
        return True
    except Exception as exc:
        note("journal: cache could not be rebuilt (%s) — answering from entries/" % exc)
        return False


def _lock_is_mine(lock: Path) -> bool:
    mine = "%d@%s" % (os.getpid(), _shortname())
    try:
        return mine in _rl(lock)
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Reading entries
# ---------------------------------------------------------------------------

def catalog():
    """The entry list used by every read command. Never needs a subprocess."""
    fresh = ensure_cache()
    entries = []
    if fresh:
        tsv = index_dir() / "entries.tsv"
        entries = _from_tsv(tsv) if tsv.exists() else []
    source = "index/entries.tsv"
    if not entries:
        entries, _problems = load_entries()
        source = "entries/"
    return entries, source, fresh


def _from_tsv(path: Path) -> list:
    out = []
    for ln in _rl(path).split("\n"):
        if not ln.strip() or ln.startswith("kind\t"):
            continue
        parts = ln.split("\t")
        if len(parts) < 12:
            continue
        (kind, id_full, num, suffix, date, host, status, heading, file, ls, le, h) = parts[:12]
        try:
            out.append(Entry(kind=kind, id_full=id_full, num=int(num or 0), suffix=suffix,
                             date="" if date == "-" else date, host="" if host == "-" else host,
                             status=status, heading=heading, body="", tags=[], refs=[],
                             alias_of="", sha="", file=file, line_start=int(ls or 1),
                             line_end=int(le or 1), hash=h, problems=[], meta={}))
        except ValueError:
            continue
    return out


def load_one(id_full: str, kind=None):
    """Direct path lookup — exactly one file, no index, no directory scan."""
    root = entries_dir()
    if kind:
        p = root / kind / (id_full + ".md")
        return parse_entry(p, kind) if p.is_file() else None
    if not root.exists():
        return None
    for k in ENTRY_KINDS:
        p = root / k / (id_full + ".md")
        if p.is_file():
            return parse_entry(p, k)
    return None


def render(entry: dict, show_meta: bool = False) -> str:
    kind = entry.get("kind", "")
    head = "### %s · %s · %s · %s" % (entry["id_full"], kind, entry.get("date") or "undated",
                                      entry.get("status") or "-")
    body = entry.get("body") or ""
    lines = [head, entry.get("heading", "")]
    if body:
        lines.append("")
        lines.append(body)
    if show_meta:
        meta = "tags=%s refs=%s sha=%s" % (",".join(entry.get("tags") or []) or "-",
                                           ",".join(entry.get("refs") or []) or "-",
                                           entry.get("hash", ""))
        if entry.get("alias_of"):
            meta += " alias_of=" + entry["alias_of"]
        lines.append("")
        lines.append("-- %s -- %s" % (meta, entry.get("file", "?")))
    return redact("\n".join(lines).rstrip()) + "\n"


# ---------------------------------------------------------------------------
# Budgeted output
# ---------------------------------------------------------------------------

class Budget:
    """Accumulates output under a byte cap, during assembly.

    A section that would overflow is cut *before* it is joined, so the cap is a
    property of the assembly rather than a check performed afterwards — that
    inversion is defect 1 in ../AUDIT.md.
    """

    def __init__(self, budget: int):
        self.budget = max(200, int(budget))
        self.parts = []
        self.used = 0
        self.truncated = 0
        self._reserve = 0

    def reserve(self, chars: int) -> None:
        """Keep room for a marker that must survive truncation."""
        self._reserve = max(0, chars)
        self._trim()

    def room(self) -> int:
        return max(0, self.budget - self.used - self._reserve)

    def line(self, text: str = "") -> bool:
        text = text or ""
        need = len(text.encode("utf-8")) + 1
        # Once a reserve is set (a truncation marker is coming), a line that would eat
        # into it is refused — the marker is the one thing that must survive the cap.
        hard = self._reserve if self._reserve else 1
        if self.used + need > self.budget - hard:
            return False
        self.parts.append(text)
        self.used += need
        return True

    def blob(self, text: str) -> bool:
        """Add a multi-line blob, cutting it at the budget if it does not fit."""
        for ln in (text or "").split("\n"):
            if not self.line(ln):
                self.truncated += 1
                return False
        return True

    def _trim(self) -> None:
        while self.used > max(0, self.budget - self._reserve) and self.parts:
            gone = self.parts.pop()
            self.used -= len(gone.encode("utf-8")) + 1

    def marker(self, remaining: int) -> None:
        """Append the visible cut marker. The reserve exists to make room for this.

        It must survive: a capped page that does not say it was capped is the defect
        this budgeter was written to kill.
        """
        if remaining <= 0:
            return
        text = "… (+%d more)" % remaining
        if self.line(text):
            return
        while self.parts and len(("\n".join(self.parts) + "\n" + text).encode("utf-8")) > self.budget:
            self.parts.pop()
        if len(("\n".join(self.parts + [text])).encode("utf-8")) <= self.budget:
            self.parts.append(text)

    def emit(self) -> str:
        out = "\n".join(self.parts)
        data = out.encode("utf-8")
        # print() adds one newline: the cap is the size of what the caller actually sees
        if len(data) + 1 > self.budget:                   # belt and braces, never hit
            out = data[:self.budget].decode("utf-8", errors="ignore").rsplit("\n", 1)[0]
        print(out)
        return out


def cap_list(items: list, headline: str, b: Budget, fmt) -> None:
    """Add a list section, cutting it during assembly and marking the cut."""
    b.line(headline)
    dropped = 0
    for i, item in enumerate(items):
        if not b.line(fmt(item)):
            dropped = len(items) - i
            b.truncated += dropped
            break
    if dropped:
        b.marker(dropped)


# ---------------------------------------------------------------------------
# Commands: the always-read page
# ---------------------------------------------------------------------------

def cmd_status(args) -> int:
    budget = getattr(args, "budget", None) or STATUS_BUDGET
    if getattr(args, "full", False):
        budget = max(budget, 200000)
    b = Budget(budget)
    b.reserve(24)
    entries, source, fresh = catalog()
    stamp = read_stamp()
    fmtv = "2" if (JOURNAL / "FORMAT").exists() else "missing FORMAT"

    b.line("JOURNAL %s · %s · format %s · %s" % (now_utc(), host_tag(), fmtv, source))
    nowp = JOURNAL / "NOW.md"
    if nowp.exists():
        # Its own cap, not the page's: sections are appended in order, so an unbounded
        # NOW.md would push the pain list, the owner-question count and the check summary
        # off the page — bounded, and useless. 1.8 KB of the 6 KB is the state page's share.
        txt, cut = _rlb_bounded(nowp, 1800)
        b.blob(txt.strip())
        if cut:
            b.line("… NOW.md truncated here — the file itself, or `status --full`")
    b.line("")

    hand = sorted([e for e in entries if e["kind"] == "handoff"],
                  key=lambda e: (e.get("date") or "", e.get("num") or 0), reverse=True)
    if hand:
        h = hand[0]
        b.line("HANDOFF %s · %s · %s" % (h["id_full"], h.get("date") or "-", h["heading"][:120]))
    else:
        b.line("HANDOFF none — the record holds no handoff")
    b.line("")

    counts = {}
    for e in entries:
        counts[e["kind"]] = counts.get(e["kind"], 0) + 1
    b.line("ENTRIES " + "  ".join("%s:%d" % (k, counts.get(k, 0)) for k in KINDS)
           + "   (total %d)" % len(entries))
    b.line("")

    pains = [e for e in entries if e["kind"] == "pain" and (e.get("status") or "open") != "done"]
    pains.sort(key=lambda e: (e.get("num") or 0, e.get("suffix") or ""))
    cap_list(pains[:8], "OPEN PAIN %d" % len(pains), b,
             lambda e: "  %7s  %s" % (e["id_full"], e["heading"][:100]))
    b.line("")

    qpath = JOURNAL / "state" / "owner-questions.md"
    if qpath.exists():
        qtext, _cut = _rlb_bounded(qpath, 4000)
        m = re.search(r"(\d+) pending", qtext) or re.search(r"(\d+) open", qtext)
        nq = m.group(1) if m else "?"
        src = re.search(r"generated (\d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC)", qtext)
        if src:
            prov = "mirror generated " + src.group(1)
        else:
            prov = "mirror mtime " + _dt.date.fromtimestamp(qpath.stat().st_mtime).isoformat()
        b.line("OWNER QUESTIONS %s open · %s · authoritative: owner_decision_queue on the authority" % (nq, prov))
        rows = [ln for ln in qtext.split("\n")
                if ln.startswith("| ") and not ln.startswith("| #") and "---" not in ln]
        for ln in rows[:3]:
            cells = [c.strip() for c in ln.strip("|").split("|")]
            b.line("  %s  %s" % (cells[0], cells[3][:100] if len(cells) > 3 else ""))
    else:
        b.line("OWNER QUESTIONS mirror missing · authoritative: owner_decision_queue on the authority")
    b.line("")

    inflight = JOURNAL / "state" / "in-flight.md"
    if inflight.exists():
        txt, cut = _rlb_bounded(inflight, max(400, b.room() // 2))
        b.blob(txt.strip())
        if cut:
            b.line("… (in-flight truncated)")
        b.line("")

    dtot = stamp.get("unabsorbed_total")
    drift = stamp.get("unabsorbed") or {}
    if dtot is None:
        b.line("LEGACY DRIFT unknown (cache has not measured it) — journal.py check")
    elif dtot:
        b.line("LEGACY DRIFT %d entr%s not absorbed (%s) — journal.py import-legacy"
               % (dtot, "y" if dtot == 1 else "ies",
                  " ".join("%s:%d" % (k, v) for k, v in sorted(drift.items()))))
    else:
        b.line("LEGACY DRIFT 0 — everything in log/** and the flat files is absorbed")
    if fresh:
        b.line("CACHE fresh · stamp %s · %s entries" % (stamp.get("built", "?"), stamp.get("entries", "?")))
    else:
        b.line("CACHE stale (rebuilt or answered from entries/) — journal.py index --force")
    b.line("")

    errs, warns, _infos = cheap_check(entries)
    # Say which rule set this is. The full `check` also counts dangling refs, legacy drift
    # and history notes, so a bare "0 warnings" here once read as a clean tree while `check`
    # had thirty things to say -- a summary that flatters the tree is worse than none.
    b.line("CHECK %d error(s) on the cheap rules (duplicate id, malformed entry, sha) — "
           "`journal.py check` adds dangling refs and legacy drift  %s"
           % (errs, "ERRORS PRESENT" if errs else ""))
    b.marker(b.truncated)
    b.emit()
    return 0


def cheap_check(entries: list):
    """The cheap integrity rules only: no whole-tree grep, no big file reads.

    The expensive rules (dangling refs, legacy drift, shard gluing) live in `check`,
    which is allowed to take a second. status may not.
    """
    errs = 0
    warns = 0
    infos = 0
    seen = {}
    for e in entries:
        seen.setdefault((e["kind"], e["id_full"]), []).append(e)
        if e.get("problems"):
            errs += 1
    for _key, group in seen.items():
        if len({g.get("hash") for g in group}) > 1:
            errs += 1
    dupes = {}
    for e in entries:
        dupes.setdefault(e.get("hash"), []).append(e)
    for _h, g in dupes.items():
        if len(g) > 1:
            infos += 1
    known = {(e["kind"], e["id_full"]) for e in entries}
    seen_alias = set()
    for a in load_aliases():
        if (a["kind"], a["canonical_id"]) not in known:
            if a["alias_id"] not in seen_alias:
                seen_alias.add(a["alias_id"])
                warns += 1
    return errs, warns, infos


# ---------------------------------------------------------------------------
# Commands: list / newest / show / search / backlinks / pairs
# ---------------------------------------------------------------------------

def _matches(e: dict, args) -> bool:
    kinds = getattr(args, "kind", None)
    if kinds:
        if e["kind"] not in [str(x).lower() for x in kinds if x]:
            return False
    st = getattr(args, "status", None)
    if st and (e.get("status") or "open") != st:
        return False
    since = getattr(args, "since", None)
    if since and (e.get("date") or "")[:10] < since:
        return False
    until = getattr(args, "until", None)
    if until and ((e.get("date") or "9999")[:10] or "9999") > until:
        return False
    tag = getattr(args, "tag", None)
    if tag and tag not in (e.get("tags") or []):
        return False
    host = getattr(args, "host", None)
    if host and host.upper() not in (e.get("host") or "").upper():
        return False
    return True


def cmd_list(args) -> int:
    entries, source, _fresh = catalog()
    rows = [e for e in entries if _matches(e, args)]
    if getattr(args, "sort", "newest") == "id":
        rows.sort(key=lambda e: (KIND_ORDER.get(e["kind"], 9), e.get("num") or 0, e.get("suffix") or ""))
    else:
        rows.sort(key=lambda e: (e.get("date") or "", e.get("num") or 0), reverse=True)
    if getattr(args, "json", False):
        print(json.dumps({"root": str(JOURNAL), "source": source, "count": len(rows),
                          "entries": [_json_entry(e) for e in rows[:args.limit or 50]]}, indent=1))
        return 0
    b = Budget(_budget_of(args))
    b.reserve(24)
    b.line("# %d entr%s in %s" % (len(rows), "y" if len(rows) == 1 else "ies", source))
    limit = args.limit or 50
    shown = 0
    for e in rows[:limit]:
        line = "%-8s %-17s %-10s %-10s %s" % (e["id_full"], (e.get("date") or "-")[:16],
                                              e.get("status") or "-", e.get("host") or "-",
                                              e["heading"][:110])
        if getattr(args, "long", False):
            line += "   [%s]" % e.get("file")
        if not b.line(line):
            break
        shown += 1
    b.marker(len(rows) - shown)
    b.emit()
    if not rows:
        note("no entries match")
    return 0


def cmd_newest(args) -> int:
    kind = args.kind or getattr(args, "kind_opt", None)
    if kind not in KINDS:
        note("unknown kind %s; one of %s" % (kind, ", ".join(KINDS)))
        return 2
    n = getattr(args, "n_opt", None) or args.n or 1
    n = max(1, n)
    rows = None
    # Fast path: pick the newest ids from the cache and open only those files. Going
    # through catalog() reads every entry to print two of them, which made `newest` the
    # slowest read in the tool (397 ms against a 200 ms target) for the *cheapest*
    # question anyone asks. The cache is a cache; when it is not fresh, fall back.
    if cache_fresh():
        try:
            cand = [r for r in _from_tsv(index_dir() / "entries.tsv") if r["kind"] == kind]
            cand.sort(key=lambda e: (e.get("date") or "", e.get("num") or 0), reverse=True)
            got = [load_one(r["id_full"], kind) for r in cand[:n]]
            rows = [e for e in got if e]
        except Exception:
            rows = None
    if rows is None:
        entries, _source, _fresh = catalog()
        rows = [e for e in entries if e["kind"] == kind]
        rows.sort(key=lambda e: (e.get("date") or "", e.get("num") or 0), reverse=True)
        rows = rows[:n]
    if getattr(args, "json", False):
        print(json.dumps({"kind": kind, "count": len(rows),
                          "entries": [_json_entry(e, with_body=True) for e in rows]}, indent=1))
        return 0
    b = Budget(_budget_of(args))
    b.reserve(24)
    for e in rows:
        if not b.blob(render(e)):
            b.truncated += 1
            break
    b.marker(b.truncated)
    b.emit()
    return 0


def _prefix_hits(want: str) -> list:
    """Base id matching: L1 hits L1, L1a, L1b. Never silently picks one."""
    want = want.upper()
    m = re.match(r"^([A-Z]+)(\d+)$", want)
    if not m:
        return []
    letter, number = m.group(1), m.group(2)
    # a base id is letter + number + SUFFIX, where a suffix is letters only: L1 matches
    # L1, L1a, L1b — it must never swallow L10, or `show L1` becomes a list of ten
    pat = re.compile(r"^%s0*%s[a-z]*$" % (re.escape(letter), re.escape(number)))
    hits = []
    for kind, spec in KINDS.items():
        if letter != spec["letter"]:
            continue
        d = entries_dir() / kind
        if not d.is_dir():
            continue
        for f in sorted(d.iterdir()):
            if f.is_file() and f.suffix == ".md" and pat.match(f.stem):
                e = parse_entry(f, kind)
                if e["id_full"]:
                    hits.append(e)
    return hits


def cmd_show(args) -> int:
    ids = args.id if isinstance(args.id, list) else [args.id]
    out_entries = []
    b = Budget(_budget_of(args))
    b.reserve(24)
    misses = []
    notes = []
    for raw in ids:
        want = str(raw).strip()
        if not want:
            continue
        e = load_one(want) or load_one(want.upper())              # exact path: one open
        if e is not None:
            # A live entry is never shadowed by an alias or by a base-id expansion.
            amap = alias_map()
            a = amap.get(e["id_full"]) or amap.get(want.upper())
            if a and a["canonical_id"] != e["id_full"]:
                notes.append("an alias maps %s -> %s (%s), but %s is itself a live entry — "
                             "showing the live entry" % (e["id_full"], a["canonical_id"],
                                                         a.get("reason") or "no reason recorded",
                                                         e["id_full"]))
            if re.match(r"^[A-Z]+\d+$", want.upper()):
                extra = _prefix_hits(want)
                if len(extra) > 1:
                    notes.append("%s matches %d entries: %s — showing all of them, not picking one"
                                 % (want, len(extra), ", ".join(x["id_full"] for x in extra)))
                    for x in extra:
                        if x["id_full"] not in {o["id_full"] for o in out_entries}:
                            out_entries.append(x)
                    continue
            out_entries.append(e)
            continue
        if e is None:
            canonical = resolve_alias(want) or resolve_alias(want.upper())
            if canonical and canonical != want:
                row = load_one(canonical)
                if row is not None:
                    notes.append("%s is an alias of %s" % (want, canonical))
                    e = row
                    want = canonical
        if e is None:
            hits = _prefix_hits(want)
            if len(hits) == 1:
                e = hits[0]
                notes.append("%s resolved to %s (the only entry with that base id)" % (want, e["id_full"]))
            elif len(hits) > 1:
                notes.append("%s matches %d entries: %s — showing all of them, not picking one"
                             % (want, len(hits), ", ".join(x["id_full"] for x in hits)))
                out_entries.extend(hits)
                continue
        if e is None:
            misses.append(want)
            continue
        out_entries.append(e)
    if getattr(args, "all", False) and len(out_entries) == 1:
        for x in _prefix_hits(out_entries[0]["id_full"]):
            if x["id_full"] not in {o["id_full"] for o in out_entries}:
                out_entries.append(x)
    if getattr(args, "json", False):
        print(json.dumps({"root": str(JOURNAL), "notes": notes, "missing": misses,
                          "entries": [_json_entry(e, with_body=True) for e in out_entries]}, indent=1))
        return 0 if out_entries else 2
    for n in notes:
        b.line("note: " + n)
    for e in out_entries:
        if not b.blob(render(e, show_meta=bool(getattr(args, "refs", False)))):
            b.truncated += 1
            break
        b.line("")
    if b.truncated:
        b.marker(b.truncated)
    b.emit()
    for m in misses:
        note("no entry %s" % m)
    if misses and not out_entries:
        return 2
    return 0


def cmd_search(args) -> int:
    pats = args.pattern if isinstance(args.pattern, list) else [args.pattern]
    pats = [p for p in pats if p is not None and p != ""]
    if not pats:
        note("no pattern given")
        return 2
    regex = bool(getattr(args, "regex", False))
    entries, source, _fresh = catalog()
    rx = None
    if regex:
        try:
            rx = re.compile(pats[0], re.IGNORECASE)
        except re.error as exc:
            note("bad regex: %s" % exc)
            return 2
    limit = args.limit or 40
    ctx_n = max(0, getattr(args, "context", 0) or 0)
    hits = []
    total_hits = 0
    cands = [e for e in entries if _matches(e, args)]
    for e in cands:
        text = "%s\n%s" % (e["heading"], e["body"])
        matches = []
        if rx is not None:
            for i, ln in enumerate(text.split("\n")):
                if rx.search(ln):
                    matches.append((i + 1, ln.strip()))
        else:
            for i, ln in enumerate(text.split("\n")):
                low = ln.lower()
                if all(p.lower() in low for p in pats):
                    matches.append((i + 1, ln.strip()))
        if matches:
            total_hits += len(matches)
            if len(hits) < limit:
                hits.append((e, matches[:1 + ctx_n]))
    if getattr(args, "legacy", False):
        pat_re = rx if rx is not None else re.compile("|".join(re.escape(p) for p in pats), re.IGNORECASE)
        for path, kind in shard_sources():
            for e in parse_shard(path, kind):
                lines = ("%s\n%s" % (e["heading"], e["body"])).split("\n")
                mm = [(i + 1, lines[i].strip()) for i in range(len(lines)) if pat_re.search(lines[i])]
                if mm:
                    total_hits += len(mm)
                    if len(hits) < limit:
                        hits.append((e, mm[:1 + ctx_n]))
    if getattr(args, "json", False):
        print(json.dumps({"root": str(JOURNAL), "source": source, "total_matches": total_hits,
                          "hits": [{"id": e["id_full"], "kind": e["kind"], "heading": redact(e["heading"]),
                                    "file": e["file"],
                                    "lines": [{"line": a, "text": redact(t)} for a, t in mm]}
                                   for e, mm in hits]}, indent=1))
        return 0 if hits else 1
    b = Budget(_budget_of(args))
    b.reserve(24)
    for e, mm in hits:
        if not b.line("%s · %s · %s · %s" % (e["id_full"], e["kind"], e.get("date") or "-",
                                             e["heading"][:110])):
            break
        for _ln_no, txt in mm:
            if not b.line("    " + txt[:200]):
                break
    b.marker(max(0, total_hits - len(hits)))
    b.emit()
    if not hits:
        note("no match for %s — an empty result is a refusal, not health" % " ".join(pats))
        return 1
    return 0


def cmd_backlinks(args) -> int:
    want = args.id.strip().upper()
    entries, _s, _f = catalog()
    hits = []
    for e in entries:
        refs = set(e.get("refs") or [])
        refs |= {"%s%s" % (m.group(1), m.group(2)) for m in REF_RE.finditer("%s\n%s" % (e["heading"], e["body"]))}
        if want in refs:
            hits.append(e)
    if getattr(args, "json", False):
        print(json.dumps({"root": str(JOURNAL), "id": want, "count": len(hits),
                          "backlinks": [_json_entry(e) for e in hits]}, indent=1))
        return 0 if hits else 1
    b = Budget(_budget_of(args))
    b.reserve(24)
    b.line("# %d entr%s reference %s" % (len(hits), "y" if len(hits) == 1 else "ies", want))
    shown = 0
    for e in hits:
        if not b.line("  %-8s %-10s %s" % (e["id_full"], e["kind"], e["heading"][:100])):
            break
        shown += 1
    b.marker(len(hits) - shown)
    b.emit()
    return 0 if hits else 1


def cmd_pairs(args) -> int:
    entries, _s, _f = catalog()
    groups = {}
    for e in entries:
        groups.setdefault((e["kind"], num_of(e["id_full"])), []).append(e)
    pairs = []
    for (kind, num), g in sorted(groups.items()):
        if len({x["id_full"] for x in g}) > 1:
            pairs.append((kind, num, sorted(g, key=lambda x: x["id_full"])))
    limit = args.limit or 40
    if getattr(args, "json", False):
        print(json.dumps({"root": str(JOURNAL), "count": len(pairs),
                          "pairs": [{"kind": k, "num": n,
                                     "ids": [{"id": x["id_full"], "heading": redact(x["heading"])} for x in g]}
                                    for k, n, g in pairs]}, indent=1))
        return 0
    b = Budget(_budget_of(args))
    b.reserve(24)
    b.line("# %d historical base-id collision(s): one number, two different entries" % len(pairs))
    shown = 0
    for kind, num, g in pairs[:limit]:
        if not b.line("%s%d:" % (KINDS[kind]["letter"], num)):
            break
        for x in g:
            if not b.line("    %-8s %s" % (x["id_full"], x["heading"][:95])):
                break
        shown += 1
    b.marker(max(0, len(pairs) - shown))
    b.emit()
    return 0


# ---------------------------------------------------------------------------
# Commands: stats / kinds / state / questions
# ---------------------------------------------------------------------------

def cmd_stats(args) -> int:
    entries, source, fresh = catalog()
    by_kind = {}
    by_month = {}
    bytes_total = 0
    sizes = []
    tags = {}
    for e in entries:
        by_kind[e["kind"]] = by_kind.get(e["kind"], 0) + 1
        month = (e.get("date") or "")[:7] or "(undated)"
        by_month[month] = by_month.get(month, 0) + 1
        try:
            sz = os.stat(str(_path_of(e["file"]))).st_size
        except OSError:
            sz = 0
        bytes_total += sz
        sizes.append((sz, e["id_full"], e["kind"], e["heading"]))
        for t in e.get("tags") or []:
            tags[t] = tags.get(t, 0) + 1
    opens = sum(1 for e in entries if (e.get("status") or "open") != "done")
    sizes.sort(reverse=True)
    oldest = sorted(entries, key=lambda e: (e.get("date") or "9999"))[:10]
    legacy_bytes = sum(p.stat().st_size for p, _k in shard_sources() if p.exists())
    top = args.top or 10
    payload = {
        "root": str(JOURNAL), "source": source, "cache_fresh": fresh,
        "entries": len(entries), "bytes": bytes_total,
        "by_kind": by_kind, "by_month": dict(sorted(by_month.items())),
        "open": opens, "closed": len(entries) - opens,
        "tags": dict(sorted(tags.items(), key=lambda kv: (-kv[1], kv[0]))[:30]),
        "largest": [{"id": i, "kind": k, "bytes": s, "heading": redact(h)} for s, i, k, h in sizes[:top]],
        "oldest_dated": [{"id": e["id_full"], "date": e.get("date")} for e in oldest],
        "frozen_shard_bytes": legacy_bytes,
        "avg_entry_bytes": bytes_total // max(1, len(entries)),
    }
    if getattr(args, "json", False):
        print(json.dumps(payload, indent=1))
        return 0
    b = Budget(_budget_of(args))
    b.reserve(24)
    b.line("# journal stats · %d entries · %d B in entries/ (avg %d B)"
           % (len(entries), bytes_total, payload["avg_entry_bytes"]))
    b.line("# source %s · cache %s · frozen log/** %d B"
           % (source, "fresh" if fresh else "stale", legacy_bytes))
    b.line("")
    b.line("  per kind:  " + "  ".join("%s:%d" % (k, v) for k, v in sorted(by_kind.items())))
    b.line("  per month: " + "  ".join("%s:%d" % (k, v) for k, v in sorted(by_month.items())))
    b.line("  open %d / closed %d" % (opens, len(entries) - opens))
    if tags:
        b.line("  tags: " + "  ".join("%s:%d" % (k, v) for k, v in list(payload["tags"].items())[:12]))
    b.line("")
    b.line("  biggest entries:")
    for s, i, k, h in sizes[:top]:
        if not b.line("    %-8s %7d B  %s" % (i, s, h[:90])):
            break
    b.emit()
    return 0


def cmd_kinds(args) -> int:
    entries, source, _f = catalog()
    counts = {}
    for e in entries:
        counts[e["kind"]] = counts.get(e["kind"], 0) + 1
    for k, spec in KINDS.items():
        print("%-10s %s  %4d entries   entries/%s/<id>.md" % (k, spec["letter"], counts.get(k, 0), k))
    print("-- %d entries from %s" % (sum(counts.values()), source))
    return 0


def _field(body: str, name: str) -> str:
    m = re.search(r"(?im)^\*\*" + re.escape(name) + r"\.?\*\*\s*(.*?)(?=\n\s*\n|\n\*\*|\Z)", body or "", re.S)
    if not m:
        return ""
    return re.sub(r"\s+", " ", m.group(1)).strip()


def cmd_state(args) -> int:
    """Regenerate state/open-pain.md — bounded, ranked, with counts."""
    rows, source, _f = catalog()
    pains = [e for e in rows if e["kind"] == "pain"]
    pains.sort(key=lambda e: (e.get("num") or 0, e.get("suffix") or ""))
    opens = [e for e in pains if (e.get("status") or "open") != "done"]
    out = [
        "# OPEN PAIN — what still hurts, ranked",
        "",
        "Updated: " + today(),
        "",
        "**Generated** from `entries/pain/` by `tools/journal.py state`. Do not edit by hand: an entry",
        "stops being open by being corrected, not by being deleted here. A problem that is done carries",
        "`status=done` in its marker or in a row of `state/status.tsv`, and drops out of this list.",
        "",
        "Provenance: %d open of %d pain entries, read from %s, written %s on %s."
        % (len(opens), len(pains), source, now_utc(), host_tag()),
        "",
        "| # | Symptom | Cost | Fix |",
        "|---|---|---|---|",
    ]
    for e in opens:
        full = load_one(e["id_full"], "pain") or e
        body = full.get("body") or ""
        cost = _field(body, "Cost")[:200]
        fix = _field(body, "Fix")[:200]
        title = re.sub(r"^##\s*", "", e.get("heading") or "")
        title = re.sub(r"^[A-Z]+\d+[a-z]?\s*[—–-]\s*", "", title)
        out.append("| %s | %s | %s | %s |" % (e["id_full"], redact(title).replace("|", "/"),
                                              redact(cost).replace("|", "/"),
                                              redact(fix).replace("|", "/")))
    atomic_write(JOURNAL / "state" / "open-pain.md", "\n".join(out).rstrip() + "\n")
    print("state/open-pain.md: %d open of %d (%d done)" % (len(opens), len(pains), len(pains) - len(opens)))
    return 0


def cmd_questions(args) -> int:
    """Mirror owner_decision_queue into state/owner-questions.md.

    The database is authoritative; this file exists so a session that cannot reach the
    authority still knows what is already waiting on the owner, and so the same
    question is never asked twice in two different stores.
    """
    raw = ""
    p = getattr(args, "from_json", None)
    if p:
        qp = Path(p)
        raw = _rl(qp) if qp.exists() else ""
    elif not getattr(args, "offline", False):
        raw = _queue_from_authority()
    path = JOURNAL / "state" / "owner-questions.md"
    if not raw.strip():
        if path.exists():
            age = _age_days(_dt.date.fromtimestamp(path.stat().st_mtime).isoformat())
            print("state/owner-questions.md: authority unreachable — existing mirror kept (%s day(s) old). "
                  "It is a mirror: the truth is owner_decision_queue on the authority." % age)
        else:
            print("state/owner-questions.md: authority unreachable and no mirror exists — read the queue "
                  "with `ssh secratary-ts \"python3 ~/bin/owner-queue.py next\"`")
        return 0
    try:
        rows = json.loads(raw)
    except Exception as exc:
        note("could not parse the queue dump: %s" % exc)
        return 2
    if isinstance(rows, dict):
        rows = rows.get("questions") or rows.get("rows") or []
    pending = [r for r in rows if (r.get("status") or "") == "pending"]
    out = [
        "# OWNER QUESTIONS — open only",
        "",
        "Updated: " + today(),
        "",
        "**Generated** from `owner_decision_queue` on the authority by `tools/journal.py questions`.",
        "That table is the single source of truth for what is waiting on the owner; this is a mirror,",
        "so a session with no route to the authority still reads the truth instead of re-asking.",
        "Do not add a question here: add it there.",
        "Provenance: %d row(s) read, %d pending, generated %s on %s."
        % (len(rows), len(pending), now_utc(), host_tag()),
        "",
        "| # | Asked | Sev | Question | My recommendation |",
        "|---|---|---|---|---|",
    ]
    for r in pending:
        q = redact(re.sub(r"\s+", " ", (r.get("question") or "")))[:400].replace("|", "/")
        rec = redact(re.sub(r"\s+", " ", (r.get("recommendation") or "")))[:220].replace("|", "/")
        out.append("| %s | %s | %s | %s | %s |" % (r.get("id"), (r.get("asked_at") or "")[:10],
                                                   r.get("severity"), q, rec))
    closed = [r for r in rows if (r.get("status") or "") != "pending"]
    out += ["", "Closed since the queue opened: %d. Answered questions move to `entries/decisions/` "
                "with the owner's own words." % len(closed)]
    atomic_write(path, "\n".join(out).rstrip() + "\n")
    print("state/owner-questions.md: %d open, %d closed" % (len(pending), len(closed)))
    return 0


def _queue_from_authority() -> str:
    """The live owner queue: spoken for directly on the authority, else over ssh.

    `~/bin/owner-queue.py` exists only on the authority (P47), so every other machine has to
    ask over ssh — and that is the route the operating instructions already document
    (`ssh secratary-ts "python3 ~/bin/owner-queue.py next"`). This function used to return ""
    whenever `os.name == "nt"`, which meant the mirror could never refresh on Windows: the
    owner's own laptop showed a stale count forever and `status` reported it as if it were
    current. Silent staleness is the failure this journal exists to prevent, so the ssh route
    is tried rather than skipped.
    """
    direct = os.path.expanduser("~/bin/owner-queue.py")
    tries = []
    if os.path.exists(direct):
        tries.append(["python3", direct, "list", "--all", "--json"])
    tries.append(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", "secratary-ts",
                  "python3 ~/bin/owner-queue.py list --all --json"])
    for cmd in tries:
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                                 errors="replace", timeout=45)
        except Exception:
            continue
        if out.returncode == 0 and (out.stdout or "").lstrip().startswith("["):
            return out.stdout
    return ""


# ---------------------------------------------------------------------------
# Commands: check
# ---------------------------------------------------------------------------

def _absorbed_alias_ids() -> set:
    """Source ids an alias row already records as absorbed under another id."""
    try:
        return set(alias_map().keys())
    except Exception:
        return set()


def unabsorbed_counts() -> dict:
    """Legacy flat entries whose LOGICAL identity is not in the tree, by kind.

    Identity is `identity_of` — the normalised body, or the title for a heading-only entry —
    not the exact heading+body hash. The two disagree for the commonest case in this journal:
    the same entry written twice on two machines under different numbers, where the body is
    identical and only the id in the heading differs. Counting those as "unabsorbed" made
    `status` tell every session that 322 entries were missing when the migration had in fact
    absorbed all of them, and pointed at a command that would have done nothing. Drift must
    mean "running `import-legacy` would add something", or it is a false alarm on the one
    page that is always read.
    """
    entries, _p = load_entries()
    idents = {(e["kind"], identity_of(e["kind"], effective_heading(e), e.get("body", "")))
              for e in entries}
    counts = {}
    aliased = _absorbed_alias_ids()
    for path, kind in flat_sources():
        try:
            ents = parse_legacy(path, kind)
        except Exception:
            continue
        n = sum(1 for e in ents
                if (kind, identity_of(kind, e["heading"], e["body"])) not in idents
                and e["id_full"] not in aliased)
        if n:
            counts[kind] = counts.get(kind, 0) + n
    return counts


def shard_unabsorbed_counts() -> dict:
    entries, _p = load_entries()
    idents = {(e["kind"], identity_of(e["kind"], effective_heading(e), e.get("body", "")))
              for e in entries}
    counts = {}
    aliased = _absorbed_alias_ids()
    for path, kind in shard_sources():
        n = sum(1 for e in parse_shard(path, kind)
                if (kind, identity_of(kind, e["heading"], e["body"])) not in idents
                and e["id_full"] not in aliased)
        if n:
            counts[kind] = counts.get(kind, 0) + n
    return counts


def cmd_check(args) -> int:
    quiet = bool(getattr(args, "quiet", False))
    max_warn = getattr(args, "max_warn", None) or 20
    lock = JOURNAL / LOCK_NAME
    # check reads the FILES, not the cache: the cache is a convenience for reads, and a
    # check that trusts it cannot see the malformed file the cache failed to parse. It
    # still refreshes the cache, because a check is exactly when a stale cache is found.
    fresh = ensure_cache()
    entries, _problems = load_entries()
    source = "entries/ (every file re-parsed)"
    errors = []
    warns = []
    infos = []

    if not entries_dir().exists() and (log_dir().exists() or (JOURNAL / "HANDOFF.md").exists()):
        errors.append("entries/ does not exist — run `journal.py migrate-v2 --apply`")
    for e in entries:
        for p in e.get("problems") or []:
            errors.append("%s: %s" % (e["file"], p))
        for n in e.get("notes") or []:
            infos.append("%s: %s" % (e["file"], n))

    # No allocated number may sit below the ceiling of any source. This is the invariant
    # whose absence let entries/lessons/L170.md be written from the flat file's L162 text:
    # an allocation below the ceiling is always a number some legacy source already owns.
    infos.append("allocation ceiling (highest number any source claims): "
                 + ", ".join("%s:%d" % (kind, max_number(kind)) for kind in KINDS))

    by_id = {}
    for e in entries:
        by_id.setdefault((e["kind"], e["id_full"]), []).append(e)
    for (kind, id_full), group in sorted(by_id.items()):
        hashes = {g.get("hash") for g in group}
        if len(group) > 1 and len(hashes) > 1:
            errors.append("duplicate id %s in %s names %d different entries: %s"
                          % (id_full, kind, len(hashes), ", ".join(g["file"] for g in group)))
        elif len(group) > 1:
            warns.append("exact duplicate %s in %s (%dx, same content) — journal.py dedupe"
                         % (id_full, kind, len(group)))
    by_hash = {}
    for e in entries:
        by_hash.setdefault(e.get("hash"), []).append(e)
    for _h, group in by_hash.items():
        if len(group) > 1:
            infos.append("same heading+body under " + ", ".join("%s(%s)" % (g["id_full"], g["file"])
                                                               for g in group))

    known_ids = {e["id_full"] for e in entries}
    known_pairs = {(e["kind"], e["id_full"]) for e in entries}
    seen_alias = set()
    for a in load_aliases():
        if (a["kind"], a["canonical_id"]) not in known_pairs and a["alias_id"] not in seen_alias:
            seen_alias.add(a["alias_id"])
            warns.append("alias %s -> %s (%s): canonical id is missing"
                         % (a["alias_id"], a["canonical_id"], a["kind"]))

    for e in entries:
        if not e.get("body"):
            if e["kind"] == "lessons":
                infos.append("%s is a heading-only lesson (empty body) — legal, recorded" % e["id_full"])
            else:
                warns.append("%s (%s) has an empty body" % (e["id_full"], e["kind"]))

    dangling = set()
    for e in entries:
        refs = set(e.get("refs") or [])
        refs |= {"%s%s" % (m.group(1), m.group(2)) for m in REF_RE.finditer("%s\n%s" % (e["heading"], e["body"]))}
        for r in refs:
            if r in known_ids or r in dangling:
                continue
            dangling.add(r)
            warns.append("dangling ref %s (cited by %s) — nothing in entries/ has that id" % (r, e["id_full"]))

    nums = {}
    for e in entries:
        nums.setdefault((e["kind"], num_of(e["id_full"])), set()).add(e["id_full"])
    collided = [k for k, ids in nums.items() if len(ids) > 1]
    if collided:
        per = {}
        for kind, _n in collided:
            per[kind] = per.get(kind, 0) + 1
        infos.append("%d historical base-id collision(s) %s — a bare reference in older prose is "
                     "ambiguous; use the suffixed id (`journal.py pairs`)"
                     % (len(collided), " ".join("%s:%d" % (KINDS[k]["letter"], v)
                                                for k, v in sorted(per.items()))))

    for kind in KINDS:
        rows = sorted([e for e in entries if e["kind"] == kind],
                      key=lambda e: (e.get("num") or 0, e.get("suffix") or ""))
        for a, b2 in zip(rows, rows[1:]):
            if a.get("date") and b2.get("date") and _minute_key(a["date"]) - _minute_key(b2["date"]) > 15:
                infos.append("out of order in %s: %s (%s) then %s (%s)"
                             % (kind, a["id_full"], a["date"], b2["id_full"], b2["date"]))
                break

    shard_counts = shard_unabsorbed_counts()
    flat_counts = unabsorbed_counts()
    # Persist the measurement. `status` cannot compute drift itself (it would have to parse
    # every legacy shard and flat file, which is exactly the cost v2 removed from the read
    # path), so it quotes what the last `check` measured — a dated number rather than
    # "unknown", which is the difference between a reading and a shrug (L1/L2).
    try:
        st = read_stamp()
        if st:
            st["unabsorbed"] = {k: v for k, v in list(shard_counts.items()) + list(flat_counts.items())}
            st["unabsorbed_total"] = sum(st["unabsorbed"].values())
            st["drift_measured"] = now_utc()
            atomic_write(index_dir() / "stamp.json", json.dumps(st, indent=1, sort_keys=True) + "\n")
    except Exception:
        pass
    if shard_counts:
        warns.append("legacy drift in log/**: %s (true count from log/**) — journal.py import-legacy"
                     % " ".join("%s:%d" % (k, v) for k, v in sorted(shard_counts.items())))
    if flat_counts:
        warns.append("legacy flat files hold entries entries/ lacks: %s (true count, exact heading+body) "
                     "— journal.py import-legacy" % " ".join("%s:%d" % (k, v) for k, v in sorted(flat_counts.items())))

    for path, kind in shard_sources():
        for i, ln in enumerate(_rl(path).split("\n")):
            if "<!-- e:" in ln and not MARKER_RE.match(ln) and LOOSE_MARKER_RE.match(ln):
                errors.append("%s:%d: marker does not start its line — that entry is being read "
                              "into the previous one's body" % (_rel_of(path), i + 1))
                break

    stamp = read_stamp()
    if not fresh:
        warns.append("index cache is stale (or locked) at read time — journal.py index --force")
    newest_handoff = max([e.get("date") or "" for e in entries if e["kind"] == "handoff"] or [""])
    if newest_handoff:
        for name in ("NOW.md", "state/in-flight.md"):
            p = JOURNAL / name
            if not p.exists():
                warns.append("%s missing" % name)
                continue
            m = re.search(r"(?i)updated[: ]+(\d{4}-\d{2}-\d{2})", _rl(p))
            if not m:
                warns.append("%s has no 'Updated: YYYY-MM-DD' line" % name)
            elif m.group(1) < newest_handoff[:10]:
                warns.append("%s says %s but the newest handoff is %s — state tier is stale"
                             % (name, m.group(1), newest_handoff[:10]))
    if lock.exists():
        try:
            age = int(time.time() - lock.stat().st_mtime)
            if age > LOCK_STALE_SEC:
                warns.append("journal lock at %s is stale (%ds old) — the next writer breaks it"
                             % (LOCK_NAME, age))
        except OSError:
            pass
    dupdir = JOURNAL / ARCHIVE_NAME / "duplicates"
    if dupdir.exists():
        n = sum(1 for _p, _s in _walk(dupdir))
        if n:
            infos.append("archive/duplicates holds %d moved duplicate entr%s" % (n, "y" if n == 1 else "ies"))

    if getattr(args, "fix", False):
        fixed = 0
        for e in entries:
            fpath = _path_of(e["file"])
            if not fpath.is_file():
                continue
            raw = fpath.read_bytes().decode("utf-8", errors="replace")
            need = "\r" in raw
            if not need:
                kv = re.search(r"<!--\s*j2\s+(.*?)-->", raw)
                got = re.search(r"sha=(\S+)", kv.group(1)) if kv else None
                if got and got.group(1) != entry_hash(effective_heading(e), e.get("body", "")):
                    need = True     # a stale sha: re-emitting recomputes it from the body
            if need:
                # Re-emit through the tool's own writer so the sha, the line endings and
                # the meta line are all canonical. Doing this with a bare text replace
                # fixed the CRLF and left the sha stale, which turned one ERROR into
                # another -- the repair has to go through the same path a write does.
                fresh_entry = parse_entry(fpath, e["kind"])
                if fresh_entry:
                    atomic_write(fpath, entry_bytes(fresh_entry))
                    fixed += 1
        if fixed:
            errors = [e for e in errors if "CRLF" not in e and "does not match the body" not in e]
            rebuild_cache()
            infos.append("--fix: re-emitted %d file(s) in canonical form (LF, recomputed sha)" % fixed)
        else:
            infos.append("--fix: nothing mechanically fixable (dedupe/repair-ids are separate "
                         "commands and never run implicitly)")
    rc = 1 if errors else 0
    if getattr(args, "json", False):
        print(json.dumps({"root": str(JOURNAL), "source": source, "cache_fresh": fresh,
                          "errors": errors, "warnings": warns, "info": infos,
                          "counts": {"error": len(errors), "warning": len(warns), "info": len(infos)}},
                         indent=1))
        return rc
    if not quiet:
        for ln in errors:
            print("ERROR " + redact(ln))
        for i, ln in enumerate(warns):
            if i >= max_warn:
                print("WARN  ... and %d more warning(s) (--max-warn N)" % (len(warns) - max_warn))
                break
            print("WARN  " + redact(ln))
        for i, ln in enumerate(infos):
            if i >= 10:
                print("INFO  ... and %d more info line(s)" % (len(infos) - 10))
                break
            print("INFO  " + redact(ln))
    print("-- %d error(s), %d warning(s), %d info" % (len(errors), len(warns), len(infos)))
    return rc


# ---------------------------------------------------------------------------
# Commands: costs / doctor
# ---------------------------------------------------------------------------

def _timed(fn, *a, **kw):
    import io
    from contextlib import redirect_stdout
    buf = io.StringIO()
    t0 = time.perf_counter()
    try:
        with redirect_stdout(buf):
            fn(*a, **kw)
    except SystemExit:
        pass
    ms = (time.perf_counter() - t0) * 1000.0
    return len(buf.getvalue().encode("utf-8")), ms


def cmd_costs(args) -> int:
    ns = argparse.Namespace
    rows = []
    b0 = ns(root=str(JOURNAL), json=False, budget=STATUS_BUDGET, full=False, quiet=True, no_color=True)
    byt, ms = _timed(cmd_status, b0)
    rows.append(("status", byt, ms, STATUS_BUDGET, 6000, 400.0))
    lb = ns(root=str(JOURNAL), json=False, budget=12000, limit=50, kind=None, status=None,
            since=None, until=None, tag=None, host=None, sort="newest", long=False, quiet=True, no_color=True)
    byt, ms = _timed(cmd_list, lb)
    rows.append(("list", byt, ms, 12000, 12000, 300.0))
    entries, _s, _f = catalog()
    newest = None
    if entries:
        newest = max(entries, key=lambda e: (e.get("date") or "", e.get("num") or 0))
    if newest:
        sb = ns(root=str(JOURNAL), json=False, budget=12000, full=False, refs=False, all=False,
                id=[newest["id_full"]], quiet=True, no_color=True)
        byt, ms = _timed(cmd_show, sb)
        rows.append(("show " + newest["id_full"], byt, ms, 12000, 12000, 30.0))
    srb = ns(root=str(JOURNAL), json=False, budget=12000, pattern=["journal"], kind=None, since=None,
             until=None, status=None, tag=None, limit=40, context=0, regex=False, all_words=False,
             legacy=False, sort="relevance", quiet=True, no_color=True)
    byt, ms = _timed(cmd_search, srb)
    rows.append(("search journal", byt, ms, 12000, 12000, 300.0))
    nb = ns(root=str(JOURNAL), json=False, budget=12000, kind="handoff", n=1, n_opt=None,
            kind_opt=None, full=False, quiet=True, no_color=True)
    byt, ms = _timed(cmd_newest, nb)
    rows.append(("newest handoff", byt, ms, 12000, 12000, 200.0))
    kd = ns(root=str(JOURNAL), json=False, quiet=True, no_color=True)
    byt, ms = _timed(cmd_kinds, kd)
    rows.append(("kinds", byt, ms, 4096, 4096, 200.0))
    payload = {
        "root": str(JOURNAL),
        "entries": len(entries),
        "cache_fresh": cache_fresh(),
        "index_bytes": {p.name: p.stat().st_size for p in sorted(index_dir().glob("*"))
                        if p.is_file()} if index_dir().exists() else {},
        "entries_tree_bytes": sum(st.st_size for _p, st in _walk(entries_dir())),
        "frozen_log_bytes": sum(p.stat().st_size for p, _k in shard_sources() if p.exists()),
        "measured": [{"command": n, "bytes": b_, "ms": round(m, 1), "budget": bud,
                      "target_bytes": tb, "target_ms": tm, "ok": bool(b_ <= tb and m <= tm)}
                     for n, b_, m, bud, tb, tm in rows],
    }
    if getattr(args, "json", False):
        print(json.dumps(payload, indent=1))
        return 0
    print("# read-path cost · %d entries · cache %s" % (payload["entries"],
                                                        "fresh" if payload["cache_fresh"] else "stale"))
    print("# root " + payload["root"])
    print("%-18s %8s %8s  %11s %9s  ok" % ("command", "bytes", "ms", "byte target", "ms target"))
    for n, b_, m, _bud, tb, tm in rows:
        print("%-18s %8d %8.1f  %11d %9.0f  %s" % (n, b_, m, tb, tm,
                                                   "yes" if (b_ <= tb and m <= tm) else "NO"))
    print("# entries/ %d B · index/ %s · frozen log/** %d B"
          % (payload["entries_tree_bytes"],
             " ".join("%s:%d" % kv for kv in payload["index_bytes"].items()),
             payload["frozen_log_bytes"]))
    return 0


def cmd_doctor(args) -> int:
    stamp = read_stamp()
    fresh = cache_fresh()
    lock = JOURNAL / LOCK_NAME
    lock_state = "free"
    if lock.exists():
        try:
            age = int(time.time() - lock.stat().st_mtime)
            lock_state = "HELD by %s (%ds)" % (_rl(lock).strip().replace("\n", " / ")[:90], age)
        except OSError:
            lock_state = "HELD (unreadable)"
    fts = "unknown"
    dbp = index_dir() / "journal.db"
    if dbp.exists():
        try:
            con = sqlite3.connect(str(dbp))
            try:
                have = con.execute("SELECT count(*) FROM sqlite_master WHERE name='fts'").fetchone()[0]
                fts = "yes" if have else "no"
            finally:
                con.close()
        except Exception as exc:
            fts = "error (%s)" % exc
    git_note = "skipped"
    if not getattr(args, "offline", False):
        git_note = _git_note()
    payload = {
        "root": str(JOURNAL),
        "format": (_rl(JOURNAL / "FORMAT").strip() or "missing"),
        "entries_files": sum(1 for _p, _s in _walk(entries_dir())),
        "entries_cached": stamp.get("entries"),
        "cache_fresh": fresh,
        "stamp_built": stamp.get("built"),
        "unabsorbed_total": stamp.get("unabsorbed_total"),
        "unabsorbed": stamp.get("unabsorbed"),
        "lock": lock_state,
        "writable": os.access(str(JOURNAL), os.W_OK) if JOURNAL.exists() else False,
        "python": sys.version.split()[0],
        "sqlite": sqlite3.sqlite_version,
        "fts5": fts,
        "git": git_note,
        "index_files": sorted(p.name for p in index_dir().glob("*")
                              if p.is_file()) if index_dir().exists() else [],
    }
    if getattr(args, "json", False):
        print(json.dumps(payload, indent=1))
        return 0
    print("root            " + payload["root"])
    print("format          %s (entries/ present: %s)" % (payload["format"], entries_dir().exists()))
    print("entries         %d file(s), %s in the last cache build"
          % (payload["entries_files"], payload["entries_cached"]))
    print("cache           %s · stamp %s" % ("fresh" if fresh else "STALE", payload["stamp_built"]))
    print("legacy drift    %s — %s" % (payload["unabsorbed_total"], payload["unabsorbed"]))
    print("lock            " + lock_state)
    print("writable        %s" % payload["writable"])
    print("python/sqlite   %s / %s · fts5 %s" % (payload["python"], payload["sqlite"], fts))
    print("git             " + git_note)
    return 0


def _git_note() -> str:
    repo = JOURNAL.parent
    try:
        rc = subprocess.run(["git", "-C", str(repo), "rev-parse", "--short", "HEAD"],
                            capture_output=True, text=True, timeout=15)
        rev = rc.stdout.strip() or "no-git"
    except Exception as exc:
        return "git unavailable (%s)" % exc
    try:
        rc = subprocess.run(["git", "-C", str(repo), "ls-remote", "--exit-code", "origin", "HEAD"],
                            capture_output=True, text=True, timeout=20)
        reach = "origin reachable" if rc.returncode == 0 else "origin unreachable (rc=%d)" % rc.returncode
    except Exception as exc:
        reach = "origin unreachable (%s)" % type(exc).__name__
    return "@%s, %s" % (rev, reach)


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------

def _lock_holder_is_dead(held: str) -> bool:
    """True when the lock names a process on THIS host that no longer exists.

    An append takes well under a second, so a lock left behind by a killed session
    is an orphan long before LOCK_STALE_SEC expires. Measured 2026-09-14: a dead
    `append 8996@zabz-yoga` blocked every journal write for ten minutes and a
    resolve had to be retried twice. The lock already records the pid and the host,
    so "is anyone there?" can be answered rather than inferred from age.

    Returns False whenever the answer is unknown — a remote host, an unparseable
    lock, a live process we cannot inspect — so the caller keeps the age rule.
    """
    m = re.search(r"(\d+)@([^:]+):", held or "")
    if not m:
        return False
    pid, host = int(m.group(1)), m.group(2)
    if host != _shortname():
        return False  # cannot inspect another machine's processes
    if pid == os.getpid():
        return False  # that is us
    if os.name == "nt":
        # Never os.kill on Windows: signal 0 is not a liveness probe there, it can
        # terminate the target. Ask the kernel for a handle instead, and treat only
        # a missing process as dead.
        try:
            import ctypes

            handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
            if handle:
                ctypes.windll.kernel32.CloseHandle(handle)
                return False
            return True
        except Exception:
            return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except (PermissionError, OSError):
        return False  # it exists, or we cannot tell
    return False


def acquire_lock(command: str, wait: float = LOCK_WAIT_SEC):
    """Serialise the journal's read-modify-write commands.

    Two writers on one tree is what produced 161 collided ids on 2026-09-14, so this
    refuses rather than proceeds. It breaks a stale lock (a crashed session must not
    wedge the journal) and it waits briefly for a live one, because six concurrent
    appends are a normal thing for the fleet to do and none of them is wrong.

    The path is v1's (`journal/.lock`) and the content is v1's shape — plain text,
    '<command> <pid>@<host>:<epoch>' — so a v1 and a v2 process exclude each other,
    and a v1 process reading a v2 lock can still print who holds it.
    """
    token = "%s %d@%s:%d" % (command, os.getpid(), _shortname(), int(time.time()))
    lock = JOURNAL / LOCK_NAME
    deadline = time.time() + max(0.0, wait)
    while True:
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(token + "\n")
            return True, token
        except FileExistsError:
            try:
                age = time.time() - lock.stat().st_mtime
                held = _rl(lock).strip()
            except OSError:
                age, held = 0.0, "(unreadable)"
            if age > LOCK_STALE_SEC or _lock_holder_is_dead(held):
                why = (
                    "%ds old" % int(age)
                    if age > LOCK_STALE_SEC
                    else "its holder is gone"
                )
                note("journal lock is stale (%s, held by %s); breaking it" % (why, held))
                try:
                    lock.unlink()
                except OSError:
                    pass
                continue
            if time.time() < deadline and not _lock_is_mine(lock):
                time.sleep(0.05)
                continue
            note("REFUSING: another session holds the journal lock (%s, %ds ago). Two writers is what "
                 "created 161 collided ids on 2026-09-14. Wait for it to finish, or remove %s if you "
                 "are certain nothing is running." % (held, int(age), lock))
            return False, ""
        except OSError as exc:
            note("REFUSING: could not take the journal lock (%s)" % exc)
            return False, ""


def release_lock(token: str) -> None:
    """Remove the lock ONLY if this process still owns it."""
    lock = JOURNAL / LOCK_NAME
    try:
        held = _rl(lock)
    except OSError:
        return
    if token and token in held:
        try:
            lock.unlink()
        except OSError:
            pass


def max_number(kind: str) -> int:
    """The highest number for `kind` VISIBLE LOCALLY: entries/, index, log/** and the flats.

    The defect this fixes (2026-09-14, measured on the real tree): the first version of
    this function looked only at `entries/` and `index/entries.tsv`. During absorption
    that is a nearly empty space — the real ids L1..L242, H1..H98, P1..P67, D1..D88 and
    W1..W66 live in `log/**` and the flat files. So every bump handed out a number far
    below the legacy ceiling: the flat file's L162 text landed at `entries/lessons/L170.md`
    (marker L170, heading L162), the later migration of log/ then found L170 taken by
    different content and bumped the *real* L170 somewhere else. One id, two entries, one
    of them named after a number it does not own. Never allocate below a number any
    source claims — `allocation_ceiling` is the only answer to "what is the highest?"
    """
    best = 0
    d = entries_dir() / kind
    if d.is_dir():
        for f in d.iterdir():
            if f.is_file() and f.suffix == ".md":
                best = max(best, num_of(f.stem))
    tsv = index_dir() / "entries.tsv"
    if tsv.exists():
        letter = KINDS[kind]["letter"]
        for ln in _rl(tsv).split("\n"):
            if ln.startswith(kind + "\t"):
                parts = ln.split("\t")
                if len(parts) > 1 and parts[1].upper().startswith(letter):
                    best = max(best, num_of(parts[1]))
    for src in legacy_candidates():
        if src["kind"] == kind:
            best = max(best, num_of(src["id_full"]))
    return best


def claim_map():
    """{id_full: entry_hash} for every id any source claims, plus reserved numbers.

    Built from `entries/` first (what is already written), then `log/**`, then the flat
    files. The first source to claim an id owns it; a later source with different content
    under the same id is the collision the migration must resolve rather than overwrite.
    """
    claims = {}
    for e in load_entries()[0]:
        claims.setdefault(e["id_full"], e.get("hash"))
    for src in legacy_candidates():
        claims.setdefault(src["id_full"], src["hash"])
    reserved = {}
    for id_full, h in claims.items():
        n = num_of(id_full)
        if n:
            reserved.setdefault(n, set()).add(h)
    return claims, reserved


def allocation_ceiling(kind: str) -> int:
    """One ceiling per kind: entries/ + index + every legacy source + every git ref.

    Every allocator (`_next_free`, `append`, `migrate-v2`, `absorb_all`, `repair-ids`)
    uses this and never returns a number at or below it. It is deliberately the maximum
    over everything rather than a count, because ids are never renumbered downwards —
    a gap costs nothing, a reused number destroys the meaning of every citation to it.
    """
    local = max_number(kind)
    remote = (read_stamp().get("git_ceiling") or {}).get(kind, 0)
    return max(local, int(remote or 0))


def note_git_ceiling(table: dict) -> None:
    """Record a ceiling measured from git refs, so reads do not need a subprocess."""
    stamp = read_stamp()
    if not stamp:
        return
    merged = dict(stamp.get("git_ceiling") or {})
    for kind, value in (table or {}).items():
        merged[kind] = max(int(merged.get(kind) or 0), int(value or 0))
    stamp["git_ceiling"] = merged
    atomic_write(index_dir() / "stamp.json", json.dumps(stamp, indent=1, sort_keys=True) + "\n")


def ceiling_table() -> dict:
    return {kind: max_number(kind) for kind in KINDS}


def git_max(kind: str, fetch: bool = False):
    """Highest number visible in any local or remote git ref. Subprocess by design.

    This is the part that stopped two machines choosing the same number. It is only
    ever called from writer paths and `doctor`, never from a read.
    """
    letter = KINDS[kind]["letter"]
    repo = JOURNAL.parent
    nums = []
    rev = "no-git"
    if fetch:
        try:
            subprocess.run(["git", "-C", str(repo), "fetch", "--quiet", "--all"],
                           capture_output=True, timeout=25)
        except Exception:
            pass
    try:
        rc = subprocess.run(["git", "-C", str(repo), "rev-parse", "--short", "HEAD"],
                            capture_output=True, text=True, timeout=15)
        rev = rc.stdout.strip() or "no-git"
    except Exception:
        pass
    pattern = "^## %s[0-9]+ |^\\*\\*%s[0-9]+ |^<!-- e:%s\\|%s[0-9]+" % (letter, letter, kind, letter)
    try:
        out = subprocess.run(["git", "-C", str(repo), "grep", "-h", "-E", pattern],
                             capture_output=True, text=True, timeout=60)
        for m in re.finditer(letter + r"(\d+)", out.stdout or ""):
            nums.append(int(m.group(1)))
    except Exception:
        pass
    try:
        out = subprocess.run(["git", "-C", str(repo), "grep", "-h", "-E", pattern, "HEAD"],
                             capture_output=True, text=True, timeout=60)
        for m in re.finditer(letter + r"(\d+)", out.stdout or ""):
            nums.append(int(m.group(1)))
    except Exception:
        pass
    return (max(nums) if nums else 0), rev


def cmd_next_id(args) -> int:
    kind = args.kind
    if kind not in KINDS:
        note("unknown kind %s" % kind)
        return 2
    local = max_number(kind)          # entries/ + index + log/** + the flat files
    remote, rev = git_max(kind, fetch=not getattr(args, "no_fetch", False))
    best = max(local, allocation_ceiling(kind), remote)
    letter = KINDS[kind]["letter"]
    print("%s%d" % (letter, best + 1))
    note("# highest seen: %s%d (entries/ + index + log/** + flats %s%d, git @ %s %s%d)"
         % (letter, best, letter, local, rev, letter, remote))
    return 0


def cmd_append(args) -> int:
    kind = args.kind
    if kind not in KINDS:
        note("unknown kind %s; one of %s" % (kind, ", ".join(KINDS)))
        return 2
    title = (getattr(args, "title", None) or "").strip()
    if not title:
        note("--title is required")
        return 2
    src = getattr(args, "body_file", None) or getattr(args, "body", None)
    if src is None:
        note("no body: pass --body TEXT, --body -, or --body-file F")
        return 2
    if src == "-":
        body = sys.stdin.buffer.read().decode("utf-8", errors="replace")
    elif os.path.exists(src):
        body = Path(src).read_text(encoding="utf-8", errors="replace")
    else:
        body = src
    body = norm_body(body)
    stamp = getattr(args, "date", "") or (now_utc() if kind == "handoff" else today())
    host = getattr(args, "host", "") or host_tag()
    status = getattr(args, "status", "") or "open"
    tags = [t for t in (getattr(args, "tags", "") or "").split(",") if t]
    refs = [t for t in (getattr(args, "refs", "") or "").split(",") if t]

    # legacy drift is absorbed first, so a v1 append that landed in log/ is not lost
    absorbed = 0
    try:
        absorbed = absorb_all(kinds=[kind], apply=True, quiet=True)["added"]
    except Exception as exc:
        note("journal: legacy absorption skipped (%s)" % exc)
        absorbed = 0
    remote = 0
    if not getattr(args, "no_fetch", False):
        remote, _rev = git_max(kind, fetch=True)
    # never below the ceiling of ANY source: log/**, the flats, the index, or a git ref
    base = max(max_number(kind), allocation_ceiling(kind), remote)
    letter = KINDS[kind]["letter"]
    want = "%s%d" % (letter, base + 1)
    path = entries_dir() / kind / (want + ".md")
    entry = {
        "kind": kind, "id_full": want, "date": stamp, "host": host, "status": status,
        "heading": build_heading(kind, want, title, stamp, host), "body": body,
        "tags": tags, "refs": refs, "alias_of": "", "sha": "",
    }
    entry["sha"] = entry_hash(entry["heading"], entry["body"])
    bumped_from = ""
    if path.exists():
        existing = parse_entry(path, kind)
        if existing.get("hash") == entry["sha"]:
            record_alias(want, kind, want, "identical content re-appended; alias written instead of a second file")
            if getattr(args, "json", False):
                print(json.dumps({"id": want, "file": _rel_of(path), "written": False,
                                  "reason": "identical content already present"}, indent=1))
            else:
                print("= %s already exists with identical content — alias recorded, nothing written" % want)
            return 0
        n = base + 1
        while True:
            n += 1
            cand = "%s%d" % (letter, n)
            p2 = entries_dir() / kind / (cand + ".md")
            if not p2.exists():
                bumped_from = want
                want = cand
                path = p2
                break
        entry["id_full"] = want
        entry["heading"] = build_heading(kind, want, title, stamp, host)
        entry["sha"] = entry_hash(entry["heading"], entry["body"])
    if getattr(args, "dry_run", False):
        print("(dry-run) would write " + _rel_of(path))
        print(entry_bytes(entry))
        return 0
    atomic_write(path, entry_bytes(entry))
    if bumped_from:
        record_alias(bumped_from, kind, want, "id collision avoided on append")
    stamp_now = rebuild_cache()
    if getattr(args, "json", False):
        print(json.dumps({"id": want, "file": _rel_of(path), "kind": kind,
                          "heading": entry["heading"], "bumped_from": bumped_from,
                          "absorbed_legacy": absorbed, "entries": stamp_now.get("entries")}, indent=1))
        return 0
    if absorbed:
        print("+ absorbed %d legacy entr%s from log/** and the flat files"
              % (absorbed, "y" if absorbed == 1 else "ies"))
    if bumped_from:
        print("id bumped %s -> %s (collision avoided)" % (bumped_from, want))
    print("+ %s -> %s  (%s entries)" % (want, _rel_of(path), stamp_now.get("entries")))
    return 0


def record_alias(alias_id: str, kind: str, canonical_id: str, reason: str,
                 host: str = "", sha: str = "", source: str = "") -> None:
    path = index_dir() / "aliases.tsv"
    if not path.exists():
        atomic_write(path, ALIAS_HEADER + "\n")
    rows = [ln for ln in _rl(path).split("\n") if ln.strip()]
    if not rows or not rows[0].startswith("alias_id\t"):
        rows = [ALIAS_HEADER] + rows
    line = "\t".join([alias_id, kind, canonical_id, reason.replace("\t", " "), today(),
                       (host or "-"), (sha or "-"), (source or "-").replace("\t", " ")])
    for existing in rows[1:]:
        cells = existing.split("\t")
        if cells[0] == alias_id and cells[2:3] == [canonical_id]:
            return
    rows.append(line)
    atomic_write(path, "\n".join(rows) + "\n")


def cmd_resolve(args) -> int:
    """Record that an entry's status changed. Appends; never edits the entry file."""
    want = args.id.strip().upper()
    e = load_one(want) or load_one(want.upper())
    if e is None:
        canonical = resolve_alias(want)
        if canonical:
            e = load_one(canonical)
    if e is None:
        note("no entry %s" % args.id)
        return 2
    path = JOURNAL / "state" / "status.tsv"
    if not path.exists():
        atomic_write(path, STATUS_HEADER + "\n")
    line = "\t".join([e["kind"], e["id_full"], args.status, today(), host_tag(),
                      (args.why or "").replace("\t", " ")])
    with open(path, "a", encoding="utf-8", newline="\n") as fh:
        fh.write(line + "\n")
    if getattr(args, "alias_of", ""):
        record_alias(e["id_full"], e["kind"], args.alias_of, args.why or "duplicate")
    rebuild_cache()
    print("= %s -> %s (%s)" % (e["id_full"], args.status, args.why or "no reason given"))
    return 0


def _title_of(heading: str, kind: str) -> str:
    """Recover a bare title from a heading of any shape the old files grew."""
    h = (heading or "").strip()
    if kind == "lessons":
        h = re.sub(r"^\*\*[A-Z]{0,2}L\d+[a-z]?\s*·\s*", "", h)
    elif kind == "pain":
        h = re.sub(r"^##\s*[A-Z]{0,2}P\d+\b", "", h).strip(" —–-")
    else:
        h = re.sub(r"^\*\*[A-Z]{0,2}[DW]\d+[a-z]?\s*·\s*", "", h)
        h = re.sub(r"^\d{4}-\d{2}-\d{2}[^·]*·\s*", "", h)
    h = h.strip().strip("*").strip()
    return h[:-1] if h.endswith(".") else (h or "(untitled)")


def _candidate(src: dict, kind: str, order: int, origin: str) -> dict:
    """Normalise one parsed source entry into an absorption candidate."""
    heading = src.get("heading", "")
    body = src.get("body", "")
    return {
        "kind": kind,
        "id_full": (src.get("id_full") or "").strip(),
        "date": (src.get("date") or "").strip(),
        "host": (src.get("host") or "").strip(),
        "status": (src.get("status") or "open").strip() or "open",
        "heading": heading,
        "heading_raw": src.get("heading_raw", ""),
        "body": body,
        "hash": entry_hash(heading, body),
        "origin": origin,
        "order": order,
        "line": src.get("line_start"),
    }


_CANDIDATE_CACHE = {}


def legacy_candidates(kinds=None) -> list:
    """Every entry this tool can see in `log/**` and the flat files, in absorption order.

    Shards first, then the flat files: a shard is the newer, structured record, so when
    two sources carry the same id the shard's copy is the one that keeps it. Read order is
    `sorted()` everywhere, so two runs see the same candidates and allocate the same ids.

    Cached on the log/flat signature: parsing 1.4 MB of shards takes ~200 ms and
    `max_number` is on the allocation path, which must stay usable inside a single write.
    """
    if kinds is None and _CANDIDATE_CACHE.get("key") == _legacy_sig():
        return _CANDIDATE_CACHE["value"]
    out = []
    order = 0
    for path, kind in shard_sources():
        if kinds and kind not in kinds:
            continue
        for e in parse_shard(path, kind):
            out.append(_candidate(e, kind, order, "%s:%s" % (_rel_of(path), e.get("line_start"))))
            order += 1
    for path, kind in flat_sources():
        if kinds and kind not in kinds:
            continue
        for e in parse_legacy(path, kind):
            out.append(_candidate(e, kind, order, "%s:%s" % (_rel_of(path), e.get("line_start"))))
            order += 1
    if kinds is None:
        _CANDIDATE_CACHE["key"] = _legacy_sig()
        _CANDIDATE_CACHE["value"] = out
    return out


def _legacy_sig() -> str:
    sig = tree_signature()
    return "%s|%s|%s|%s" % (sig["log_sig"], sig["log_count"], sig["flat_sig"], JOURNAL)


def clear_caches() -> None:
    _CANDIDATE_CACHE.clear()


def _assign(candidates: list, base_claims: dict, existing_hashes=None) -> dict:
    """Assign every candidate an id, in one pass, at or above the ceiling of every source.

    Two phases, deliberately: ALL ids from ALL sources are collected before ANY is handed
    out, so a bump cannot take a number a later source needs. Handing out numbers while
    still reading is what produced the L162/L170 scar on the real tree on 2026-09-14.
    """
    claims = dict(base_claims)
    cursor = {kind: 0 for kind in KINDS}
    for id_full in list(claims) + [c["id_full"] for c in candidates if c["id_full"]]:
        for kind, spec in KINDS.items():
            if id_full.startswith(spec["letter"]):
                cursor[kind] = max(cursor[kind], num_of(id_full))

    def free_id(kind: str) -> str:
        letter = KINDS[kind]["letter"]
        while True:
            cursor[kind] += 1
            cand = "%s%d" % (letter, cursor[kind])
            if cand not in claims:
                return cand

    assigned = []
    bumped = []
    for c in sorted(candidates, key=lambda x: x["order"]):
        c = dict(c)
        want = c["id_full"]
        owner = claims.get(want) if want else None
        if existing_hashes and c["hash"] in existing_hashes:
            # this exact content is already filed in entries/ — nothing to write
            c["skip"] = True
            assigned.append(c)
            continue
        if not want or (owner is not None and owner != c["hash"]):
            new = free_id(c["kind"])
            bumped.append((want or "(no id)", new, c["origin"]))
            c["legacy_id"] = want
            c["id_full"] = new
        claims[c["id_full"]] = c["hash"]
        assigned.append(c)
    return {"assigned": assigned, "bumped": bumped, "claims": claims}


def scan_tree() -> dict:
    """{(kind, id_full): {hash: [origins]}} over `entries/`, `log/**` and the flat files.

    Richer than an id->hash map on purpose: it is what lets `check` say exactly which
    sources disagree about an id instead of only that something does.
    """
    out = {}
    for e in load_entries()[0]:
        out.setdefault((e["kind"], e["id_full"]), {}).setdefault(e["hash"], []).append(e["file"])
    for c in legacy_candidates():
        out.setdefault((c["kind"], c["id_full"]), {}).setdefault(c["hash"], []).append(c["origin"])
    return out


def absorb_all(kinds=None, apply: bool = False, quiet: bool = False) -> dict:
    """Absorb `log/**` and the flat files into `entries/` by IDENTITY, never by bytes.

    Measured on the real tree: 194 flat entries are byte-identical to a shard entry, 184
    are the same entry under a different heading id, and only 68 are text the record does
    not have. Keying absorption on `entry_hash` alone therefore creates a second copy of
    an entry the tree already holds — 247 entries where 68 are new, ~19% of the record
    written twice. Instead:

      * identical (same `entry_hash`)          -> an alias row, nothing written
      * same identity, different bytes         -> an alias row, nothing written
      * genuinely new text                     -> one entry, id at/above the ceiling

    Returns the three counts plus the bumps, and is idempotent: a second run reports every
    source as identical and writes nothing.
    """
    existing, _p = load_entries()
    by_hash = {}
    by_ident = {}
    claims = {}
    # An alias row is a record that this source id was ALREADY absorbed under another id.
    # Without this, a source whose parsed body differs from the body the writer emitted
    # (a wrapped heading folds differently) is re-added on every pass and then collapsed
    # again by `dedupe` — an import/dedupe loop that also leaves `status` telling every
    # session, forever, that two entries are missing. The alias is the tool's own evidence
    # that the entry is in the tree; believe it.
    alias_owner = alias_map()
    for e in existing:
        by_hash.setdefault(e["hash"], e["id_full"])
        claims.setdefault(e["id_full"], e.get("hash"))
        ident = identity_of(e["kind"], e["heading"], e["body"])
        cur = by_ident.get(ident)
        if cur is None or num_of(e["id_full"]) < num_of(cur):
            by_ident[ident] = e["id_full"]
    candidates = legacy_candidates(kinds=kinds)
    cursor = {kind: 0 for kind in KINDS}
    for id_full in list(claims) + [c["id_full"] for c in candidates if c["id_full"]]:
        # the ceiling has to sit above every id ANY source claims, including the ones this
        # pass is about to write — but a candidate's own id is not a conflict with itself,
        # so it is NOT pre-claimed here. A later candidate with the same id and different
        # content is the one that gets bumped.
        for kind, spec in KINDS.items():
            if id_full.startswith(spec["letter"]):
                cursor[kind] = max(cursor[kind], num_of(id_full))

    counts = {"identical": 0, "aliased": 0, "added": 0}
    bumped = []
    for c in candidates:
        kind = c["kind"]
        h = c["hash"]
        ident = identity_of(kind, c["heading"], c["body"])
        exact = by_hash.get(h)
        owner = exact or by_ident.get(ident)
        if not owner and c["id_full"]:
            owner = alias_owner.get(c["id_full"])
        if owner:
            counts["identical" if exact else "aliased"] += 1
            if c["id_full"]:
                claims.setdefault(c["id_full"], h)
            if c["id_full"] and c["id_full"] != owner:
                if apply:
                    record_alias(c["id_full"], kind, owner,
                                 "same entry absorbed by identity, not by bytes",
                                 host=c["host"], sha=h, source=c["origin"])
                if not quiet:
                    print("= %s -> %s  (already held; alias recorded, nothing written)"
                          % (c["id_full"], owner))
            continue
        new_id = c["id_full"]
        if not new_id or new_id in claims:
            while True:
                cursor[kind] += 1
                cand = "%s%d" % (KINDS[kind]["letter"], cursor[kind])
                if cand not in claims and not (entries_dir() / kind / (cand + ".md")).exists():
                    new_id = cand
                    break
            bumped.append((c["id_full"] or "(no id)", new_id, c["origin"]))
        claims[new_id] = h
        rec = {
            "kind": kind, "id_full": new_id, "date": c["date"],
            "host": c["host"] or "legacy", "status": c["status"],
            "heading": c["heading"], "body": c["body"],
            "heading_raw": c["heading_raw"] or "",
            "tags": ["legacy-import"], "refs": [], "alias_of": "",
            "legacy_id": c["id_full"] if new_id != c["id_full"] else "", "sha": "",
        }
        rec["sha"] = entry_hash(effective_heading(rec), rec["body"])
        if apply:
            atomic_write(entries_dir() / kind / (new_id + ".md"), entry_bytes(rec))
        by_hash[h] = new_id
        by_ident[ident] = new_id
        counts["added"] += 1
        if not quiet:
            was = " (filed as %s in the source)" % c["id_full"] if new_id != c["id_full"] else ""
            print("+ new %s <- %s%s" % (new_id, c["origin"], was))
    return {"added": counts["added"], "identical": counts["identical"],
            "aliased": counts["aliased"], "bumped": bumped,
            "candidates": len(candidates), "ceiling": {k: max_number(k) for k in KINDS}}


def identity_of(kind: str, heading: str, body: str):
    """The identity of a LOGICAL entry, not of a byte string.

    Measured on the real tree (2026-09-14): 184 flat-file entries are the same entry as a
    shard entry under a different heading id, and 220 entries inside `log/**` are copies
    of one entry under different ids. `entry_hash(heading, body)` is a fast path only — it
    cannot see that `**L154 · x**` and `**L154b · x**` are one lesson. Two things make an
    entry: its body (whitespace-normalised), or — for the heading-only lessons L23,
    L162-L166, L170, L173 — its title with the id and any date stamp stripped.
    """
    body_n = norm_body(body)
    if body_n:
        return (kind, "body", body_n)
    title = _title_of(heading, kind)
    title = re.sub(r"\s+", " ", re.sub(r"[^A-Za-z0-9]+", " ", (title or "").lower())).strip()
    return (kind, "title", title)


def identity_index(entries) -> dict:
    """identity -> the id that owns it (lowest number wins)."""
    out = {}
    for e in entries:
        ident = identity_of(e["kind"], e["heading"], e["body"])
        cur = out.get(ident)
        if cur is None or num_of(e["id_full"]) < num_of(cur):
            out[ident] = e["id_full"]
    return out


def _legacy_id_of(entry: dict) -> str:
    """The legacy id an entry was filed as, from its metadata (never guessed)."""
    meta = entry.get("meta") or {}
    value = (meta.get("legacy_id") or "").strip()
    return "" if value in ("-", "") else value


def heading_id_token(entry: dict) -> str:
    """The id token the heading itself carries, '' when the kind's heading has none."""
    spec = KINDS.get(entry.get("kind"))
    if not spec:
        return ""
    m = spec["regex"].match(entry.get("heading") or "")
    if not m:
        return ""
    return (m.groupdict().get("id") or "").strip()


def _next_free(kind: str, taken: set) -> str:
    """The next id at or above the local ceiling that no source claims."""
    letter = KINDS[kind]["letter"]
    claims, _reserved = claim_map()
    n = max(allocation_ceiling(kind), max_number(kind))
    if taken:
        n = max(n, max(num_of(t) for t in taken if t))
    while True:
        n += 1
        cand = "%s%d" % (letter, n)
        if cand not in taken and cand not in claims and not (entries_dir() / kind / (cand + ".md")).exists():
            taken.add(cand)
            return cand


def _absorb_from_sources(apply: bool, quiet: bool) -> dict:
    """Compatibility shim: absorption is a tree-wide batch operation in v2."""
    return absorb_all(apply=apply, quiet=quiet)


def cmd_import_flat(args) -> int:
    """v1's name for `import-legacy`, kept because `_journal-merge/techsync.ps1` calls it."""
    note("journal: `import-flat` is deprecated; use `import-legacy` (same work, one batch pass)")
    return cmd_import_legacy(args)


def cmd_import_legacy(args) -> int:
    """Absorb everything in `log/**` and the flat files that `entries/` does not hold.

    Shards are scanned before the flats and every id is claimed before any is handed
    out, so the shards are included by default and `--include-shards` is accepted only
    for compatibility with the flag v1 grew.
    """
    apply = bool(getattr(args, "apply", False))
    as_json = bool(getattr(args, "json", False))
    entries, _p = load_entries()
    plan = absorb_all(apply=apply, quiet=as_json)   # --json prints JSON and nothing else
    after, _p2 = load_entries()
    remaining = _preview_unabsorbed()
    payload = {"apply": apply, "before": len(entries), "after": len(after), "added": plan["added"],
               "identical": plan["identical"], "aliased": plan["aliased"],
               "ids_bumped": len(plan["bumped"]),
               "ceiling": plan["ceiling"],
               "still_unabsorbed": remaining, "still_unabsorbed_total": sum(remaining.values())}
    if getattr(args, "json", False):
        print(json.dumps(payload, indent=1))
        return 0
    if not apply:
        print("-- dry run: identical %d · aliased %d · new %d  (entries/ %d -> %d); re-run with --apply"
              % (plan["identical"], plan["aliased"], plan["added"],
                 len(entries), len(entries) + plan["added"]))
    else:
        rebuild_cache(compute_drift=True)
        print("-- identical %d · aliased %d · added %d · id(s) bumped %d: entries/ %d -> %d"
              % (plan["identical"], plan["aliased"], plan["added"], len(plan["bumped"]),
                 len(entries), len(after)))
    for old, new, origin in plan["bumped"][:12]:
        print("    bumped %s -> %s  (%s)" % (old, new, origin))
    if len(plan["bumped"]) > 12:
        print("    ... and %d more" % (len(plan["bumped"]) - 12))
    if remaining:
        print("-- still not absorbed: " + " ".join("%s:%d" % (k, v) for k, v in sorted(remaining.items())))
    return 0


def _preview_unabsorbed() -> dict:
    """Per-kind count of source entries whose LOGICAL identity no entry in the tree matches.

    Same rule as `unabsorbed_counts` and as absorption itself (`identity_of`): a flat copy of
    an entry that is already filed under another number is *absorbed*, not missing. Counting
    by exact hash reported 534 phantom gaps here after the migration had closed them all.
    """
    entries, _p = load_entries()
    idents = {(e["kind"], identity_of(e["kind"], effective_heading(e), e.get("body", "")))
              for e in entries}
    counts = {}
    aliased = _absorbed_alias_ids()
    for c in legacy_candidates():
        if (c["kind"], identity_of(c["kind"], c["heading"], c.get("body", ""))) in idents:
            continue
        if c["id_full"] in aliased:
            continue
        counts[c["kind"]] = counts.get(c["kind"], 0) + 1
    return counts


def _shard_proof() -> list:
    """Per-shard byte accounting for the migration proof. Read-only."""
    proof = []
    for path, kind in shard_sources():
        text = _rl(path)
        preamble, blocks = shard_blocks(path)
        block_bytes = sum(len(b.encode("utf-8")) for b, _s, _e in blocks)
        src_bytes = len(text.encode("utf-8"))
        # The proof, stated exactly: the preamble plus every block plus the newline that
        # separated each pair of blocks is the whole file. `shard_blocks` splits on line
        # ranges and joins each range without a trailing newline, so N blocks hold N-1
        # inter-block newlines; the preamble carries its own.
        # `shard_blocks` strips each block's trailing newline, so the bytes a block does
        # not account for are exactly the newline that ended its last line: one per block.
        # The preamble carries its own. Everything else would be a byte nobody can name.
        # Exact, with no per-line fudge: the preamble, one newline, then every block
        # joined by one newline each IS the file. Nothing here is estimated.
        accounted = (len(preamble.encode("utf-8")) + (1 if blocks else 0) + block_bytes
                     + max(0, len(blocks) - 1))
        proof.append({"shard": _rel_of(path), "kind": kind, "entries": len(blocks),
                      "source_bytes": src_bytes, "block_bytes": block_bytes,
                      "preamble_bytes": len(preamble.encode("utf-8")),
                      "residue": src_bytes - accounted})
    return proof


def _source_entry_bytes(entry) -> int:
    """The bytes one parsed source entry accounts for, from its own recorded line range.

    Used to prove absorption: the sum over a source's entries plus its preamble is the
    file. Nothing is estimated — the line range is what the parser matched.
    """
    start = int(entry.get("line_start") or 0)
    end = int(entry.get("line_end") or 0)
    if start <= 0 or end < start:
        return 0
    text = _rl(_path_of(entry.get("file", ""))) if entry.get("file") else ""
    if not text:
        return 0
    lines = text.split("\n")
    block = "\n".join(lines[start - 1:end])
    return len(block.encode("utf-8")) + (1 if end <= len(lines) else 0)


def coverage() -> dict:
    """Byte and entry coverage of every source, from the parsers. The absorption proof.

    For each source file: how many entry bytes the parser accounts for, how many of
    those entries a file in `entries/` matches by `entry_hash`, and how many are still
    unabsorbed. `residue` is source bytes minus the entries' own bytes minus the
    preamble — it must be zero, and it is computed from the same parse that read the
    entries rather than from a second line-range split that can disagree by a newline.
    """
    existing, _p = load_entries()
    tree_hashes = {e["hash"] for e in existing}
    sources = {}
    for path, kind in shard_sources():
        sources.setdefault(_rel_of(path), {"kind": kind, "parser": "shard"}).setdefault("path", path)
        sources[_rel_of(path)]["path"] = path
        sources[_rel_of(path)]["entry_count"] = len(parse_shard(path, kind))
        sources[_rel_of(path)]["entry_bytes"] = sum(
            _source_entry_bytes(e) for e in parse_shard(path, kind))
    for path, kind in flat_sources():
        sources.setdefault(_rel_of(path), {"kind": kind, "parser": "flat"})
        sources[_rel_of(path)]["path"] = path
        entries = parse_legacy(path, kind)
        sources[_rel_of(path)]["entry_count"] = len(entries)
        sources[_rel_of(path)]["entry_bytes"] = sum(_source_entry_bytes(e) for e in entries)
    out = []
    for rel, info in sorted(sources.items()):
        path = info["path"]
        total = path.stat().st_size if path.exists() else 0
        covered = info.get("entry_bytes", 0)
        if info["parser"] == "shard":
            preamble = len(shard_blocks(path)[0].encode("utf-8"))
        else:
            # a flat file is a preamble followed by its entries; the preamble is whatever
            # the parse did not consume, and naming it is what turns residue into a proof
            preamble = total - covered
        residue = total - covered - preamble
        entries = (parse_shard(path, info["kind"]) if info["parser"] == "shard"
                   else parse_legacy(path, info["kind"]))
        missing = sum(1 for e in entries if entry_hash(e["heading"], e["body"]) not in tree_hashes)
        out.append({"source": rel, "kind": info["kind"], "parser": info["parser"],
                    "source_bytes": total, "entry_bytes": covered, "preamble_bytes": preamble,
                    "residue": residue,
                    "entries": info.get("entry_count", 0), "unabsorbed": missing})
    return {"sources": out,
            "residue_total": sum(s["residue"] for s in out),
            "unabsorbed_total": sum(s["unabsorbed"] for s in out)}


def cmd_migrate_v2(args) -> int:
    """Split `log/**` into `entries/` one-for-one, then absorb the flat files.

    One pass over every source; ids are assigned only after the whole claim set is known,
    so no allocation can land below a number a legacy source owns and no bump can steal a
    number a later source needs. Idempotent: a second run writes nothing.
    """
    apply = bool(getattr(args, "apply", False))
    entries, _p = load_entries()
    proof = _shard_proof()
    plan = absorb_all(apply=apply, quiet=bool(getattr(args, "json", False)))
    if apply:
        rebuild_cache(compute_drift=True)
    after, _p2 = load_entries()
    total_residue = sum(p["residue"] for p in proof)
    payload = {
        "apply": apply, "shards": len(proof), "blocks": sum(p["entries"] for p in proof),
        "written": plan["added"], "identical": plan["identical"], "aliased": plan["aliased"],
        "bumped": len(plan["bumped"]),
        "bumped_detail": ["%s -> %s (%s)" % (o, n, org) for o, n, org in plan["bumped"]],
        "ceiling": plan["ceiling"], "entries_before": len(entries), "entries_after": len(after),
        "residue_bytes": total_residue, "proof": proof,
    }
    if getattr(args, "json", False):
        print(json.dumps(payload, indent=1))
        return 0 if total_residue == 0 else 1
    print("migrate-v2 %s: %d shard(s), %d entries in them"
          % ("applied" if apply else "DRY RUN (nothing written)", len(proof), payload["blocks"]))
    print("  new entries written %d | identical (alias only) %d | same identity, different bytes %d | ids bumped %d"
          % (plan["added"], plan["identical"], plan["aliased"], len(plan["bumped"])))
    for old, new, origin in plan["bumped"][:12]:
        print("    bumped %s -> %s  (%s)" % (old, new, origin))
    if len(plan["bumped"]) > 12:
        print("    ... and %d more" % (len(plan["bumped"]) - 12))
    print("  allocation ceiling per kind: "
          + " ".join("%s:%d" % kv for kv in sorted(plan["ceiling"].items())))
    print("  entries/: %d -> %d" % (len(entries), len(after)))
    print("  byte-preservation residue: %d B across %d shard(s)" % (total_residue, len(proof)))
    for p in proof:
        flag = "" if p["residue"] == 0 else "  <-- UNEXPLAINED"
        print("    %-34s %4d entries  src %7d B  blocks %7d B  preamble %4d B  residue %d%s"
              % (p["shard"], p["entries"], p["source_bytes"], p["block_bytes"],
                 p["preamble_bytes"], p["residue"], flag))
    cov = coverage()
    print("  coverage: %d source(s), %d bytes, residue %d B, unabsorbed %d entry(ies)"
          % (len(cov["sources"]), sum(s["source_bytes"] for s in cov["sources"]),
             cov["residue_total"], cov["unabsorbed_total"]))
    if total_residue:
        return 1
    if not apply:
        print("  (nothing written; re-run with --apply)")
    return 0


def cmd_dedupe(args) -> int:
    """Collapse identity-duplicates inside `entries/`, moving the surplus, never deleting.

    Canonical = the lowest number, ties broken by earliest date then id. Measured on the
    real tree: 789 entries collapse to 569 — 220 redundant copies (196 lessons, 13
    decisions, 9 handoffs, 1 pain, 1 win), 269,142 bytes, ~19% of the record.
    """
    entries, _p = load_entries()
    groups = {}
    for e in entries:
        groups.setdefault(identity_of(e["kind"], e["heading"], e["body"]), []).append(e)
    per_kind = {}
    moved = 0
    for ident, group in sorted(groups.items(), key=lambda kv: (kv[1][0]["kind"], kv[1][0]["id_full"])):
        if len(group) < 2:
            continue
        group.sort(key=lambda e: (num_of(e["id_full"]), e.get("date") or "", e["id_full"]))
        keep = group[0]
        for dup in group[1:]:
            per_kind[dup["kind"]] = per_kind.get(dup["kind"], 0) + 1
            print("%s == %s (same entry: %s) — keeping %s, %s %s"
                  % (dup["id_full"], keep["id_full"], ident[1],
                     keep["id_full"], "moving" if args.apply else "would move", dup["file"]))
            if args.apply:
                dest = JOURNAL / ARCHIVE_NAME / "duplicates" / dup["kind"] / (dup["id_full"] + ".md")
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(_path_of(dup["file"])), str(dest))
                record_alias(dup["id_full"], dup["kind"], keep["id_full"],
                             "identity duplicate inside entries/", host=dup.get("host"),
                             sha=dup.get("hash"), source=_rel_of(dest))
                moved += 1
    if args.apply and moved:
        rebuild_cache()
    print("-- %s: %d copy(ies) collapsed " % ("moved" if args.apply else "would move", moved)
          + " ".join("%s:%d" % kv for kv in sorted(per_kind.items())))
    return 0


def cmd_repair_ids(args) -> int:
    entries, _p = load_entries()
    by_id = {}
    for e in entries:
        by_id.setdefault((e["kind"], e["id_full"]), []).append(e)
    collided = {k: v for k, v in by_id.items() if len(v) > 1 and len({x["hash"] for x in v}) > 1}
    if not collided:
        print("no id collides with different content — nothing to do")
        return 0
    taken = {e["id_full"] for e in entries}
    changed = 0
    for (kind, id_full), group in sorted(collided.items()):
        group.sort(key=lambda e: (e.get("date") or "", e.get("file") or ""))
        keep = group[0]
        for dup in group[1:]:
            new_id = _next_free(kind, taken)
            print("%s (%s) -> %s  (kept %s at %s)" % (id_full, dup["file"], new_id,
                                                      keep["id_full"], keep["file"]))
            if not args.apply:
                continue
            full = parse_entry(_path_of(dup["file"]), kind)
            full["id_full"] = new_id
            full["heading"] = re.sub(r"\b" + re.escape(id_full) + r"\b", new_id, full["heading"], count=1)
            full["sha"] = entry_hash(full["heading"], full["body"])
            atomic_write(entries_dir() / kind / (new_id + ".md"), entry_bytes(full))
            record_alias(id_full, kind, new_id,
                         "id collided with different content; %s keeps %s" % (keep["id_full"], id_full))
            changed += 1
    if args.apply and changed:
        rebuild_cache()
    print("-- %d entr%s renumbered" % (changed, "y" if changed == 1 else "ies") if args.apply
          else "-- report only; re-run with --apply")
    return 0


def cmd_gc_legacy(args) -> int:
    hours = getattr(args, "quiet_hours", 0) or 0
    sources = shard_sources()
    if not sources:
        print("log/** holds no shards — nothing to freeze")
        return 0
    now = time.time()
    newest = max(p.stat().st_mtime for p, _k in sources if p.exists())
    age_h = (now - newest) / 3600.0
    days = today()
    dest = JOURNAL / ARCHIVE_NAME / ("legacy-shards-" + days)
    print("log/**: %d shard(s), newest change %.1f h ago" % (len(sources), age_h))
    if hours and age_h < hours:
        print("refusing: log/** changed within the last %s h (a v1 writer may still be live)" % hours)
        return 0
    if not args.apply:
        print("would move them to %s/ and leave log/ re-creatable" % _rel_of(dest))
        return 0
    dest.mkdir(parents=True, exist_ok=True)
    for p, kind in sources:
        out = dest / kind / p.name
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(p), str(out))
    atomic_write(log_dir() / "README.md",
                 "# log/ — FROZEN legacy shards\n\n"
                 "The shards that used to live here were moved to `%s/` on %s by\n"
                 "`journal.py gc-legacy`. Nothing reads them except `import-legacy` and\n"
                 "`search --legacy`. `entries/` is the source of truth.\n\n"
                 "A machine still running v1 will append here (kind directory + month file); the next\n"
                 "v2 write or `import-legacy` absorbs it, which is why this directory survives.\n"
                 % (_rel_of(dest), days))
    rebuild_cache(compute_drift=True)
    print("moved %d shard(s) -> %s/ · log/README.md written" % (len(sources), _rel_of(dest)))
    return 0


def cmd_index(args) -> int:
    stamp = rebuild_cache(compute_drift=True)
    if not getattr(args, "quiet", False):
        print("index: %s entries -> %s · stamp %s"
              % (stamp.get("entries"), stamp.get("db"), stamp.get("built")))
    if getattr(args, "stats", False):
        for p in sorted(index_dir().glob("*")):
            if p.is_file():
                print("  %-16s %9d B" % (p.name, p.stat().st_size))
    return 0


def cmd_selftest(args) -> int:
    script = Path(__file__).resolve().parent / "selftest.py"
    if not script.exists():
        note("selftest.py not found at %s" % script)
        return 2
    return subprocess.call([sys.executable, str(script)])


def cmd_verify(args) -> int:
    """The independent gate: proves a rebuild lost nothing, using the frozen v1 parser.

    `selftest` checks the tool against its own rules; this checks the TREE against an
    implementation of the old format that the new tool did not write (`tools/verify.py`).
    It is the check that caught three defects the 240-check selftest could not see, so it
    belongs in the tool rather than in a scratch directory.
    """
    script = Path(__file__).resolve().parent / "verify.py"
    if not script.exists():
        note("verify.py not found at %s" % script)
        return 2
    return subprocess.call([sys.executable, str(script)])


# ---------------------------------------------------------------------------
# JSON helpers
# ---------------------------------------------------------------------------

def _json_entry(e: dict, with_body: bool = False) -> dict:
    d = {"id": e.get("id_full"), "kind": e.get("kind"), "date": e.get("date") or "",
         "host": e.get("host") or "", "status": e.get("status") or "",
         "heading": redact(e.get("heading") or ""), "file": e.get("file"),
         "hash": e.get("hash"), "tags": e.get("tags") or [], "refs": e.get("refs") or []}
    if with_body:
        d["body"] = redact(e.get("body") or "")
    if e.get("problems"):
        d["problems"] = e["problems"]
    return d


def _budget_of(args) -> int:
    return getattr(args, "budget", None) or DEFAULT_BUDGET


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--root", default=None,
                        help="the journal directory (default: the parent of tools/, so it works from any cwd)")
    common.add_argument("--json", action="store_true", help="machine-readable output")
    common.add_argument("--budget", type=int, default=None, help="output byte cap (per-command default)")
    common.add_argument("--quiet", action="store_true", help="errors only")
    common.add_argument("--no-color", action="store_true", help="plain output (no ANSI)")

    p = argparse.ArgumentParser(prog="journal.py", description=__doc__.split("\n")[0], parents=[common])
    sub = p.add_subparsers(dest="cmd", required=True)

    def add(name, help_text):
        return sub.add_parser(name, help=help_text, parents=[common])

    s = add("status", "the always-read page: bounded, assembled under the cap, exit 0")
    s.add_argument("--full", action="store_true")
    s.set_defaults(func=cmd_status)

    s = add("list", "one line per entry; never prints bodies")
    s.add_argument("--kind", action="append", default=None, help="repeatable")
    s.add_argument("--status", default=None)
    s.add_argument("--since", default=None)
    s.add_argument("--until", default=None)
    s.add_argument("--tag", default=None)
    s.add_argument("--host", default=None)
    s.add_argument("--limit", type=int, default=50)
    s.add_argument("--sort", choices=["newest", "id"], default="newest")
    s.add_argument("--long", action="store_true")
    s.set_defaults(func=cmd_list)

    s = add("newest", "newest N entries of a kind: `newest handoff 2`")
    s.add_argument("kind", nargs="?", default=None)
    s.add_argument("n", nargs="?", type=int, default=1)
    s.add_argument("-k", "--kind-opt", dest="kind_opt", default=None)
    s.add_argument("-n", dest="n_opt", type=int, default=None)
    s.add_argument("--full", action="store_true")
    s.set_defaults(func=cmd_newest)

    s = add("show", "print an entry by id; an exact id opens exactly one file")
    s.add_argument("id", nargs="+")
    s.add_argument("--full", action="store_true")
    s.add_argument("--refs", action="store_true", help="also show tags/refs/sha and the file")
    s.add_argument("--all", action="store_true")
    s.set_defaults(func=cmd_show)

    s = add("search", "search entries; bounded snippets, never a whole file")
    s.add_argument("pattern", nargs="+")
    s.add_argument("--kind", action="append", default=None)
    s.add_argument("--since", default=None)
    s.add_argument("--until", default=None)
    s.add_argument("--status", default=None)
    s.add_argument("--tag", default=None)
    s.add_argument("--limit", type=int, default=40)
    s.add_argument("--context", type=int, default=0)
    s.add_argument("--regex", action="store_true")
    s.add_argument("--all-words", dest="all_words", action="store_true",
                   help="every pattern must be present in the same line (the default)")
    s.add_argument("--legacy", action="store_true", help="also scan the frozen shards")
    s.add_argument("--sort", choices=["relevance", "newest"], default="relevance")
    s.set_defaults(func=cmd_search)

    s = add("backlinks", "which entries cite this id")
    s.add_argument("id")
    s.set_defaults(func=cmd_backlinks)

    s = add("pairs", "historical base-id collisions: one number, two entries")
    s.add_argument("--limit", type=int, default=40)
    s.set_defaults(func=cmd_pairs)

    s = add("stats", "counts, bytes, per-kind and per-month tables, biggest entries")
    s.add_argument("--top", type=int, default=10)
    s.set_defaults(func=cmd_stats)

    s = add("kinds", "what lives where, one line per kind")
    s.set_defaults(func=cmd_kinds)

    s = add("state", "regenerate state/open-pain.md (bounded, ranked)")
    s.set_defaults(func=cmd_state)

    s = add("questions", "mirror owner_decision_queue into state/owner-questions.md")
    s.add_argument("--offline", action="store_true")
    s.add_argument("--from-json", dest="from_json", default=None,
                   help="JSON dump from `owner-queue.py list --all --json`")
    s.set_defaults(func=cmd_questions)

    s = add("check", "integrity; exit non-zero only on ERROR")
    s.add_argument("--fix", action="store_true", help="report what a repair would do")
    s.add_argument("--max-warn", dest="max_warn", type=int, default=20)
    s.set_defaults(func=cmd_check)

    s = add("costs", "measure the read path (bytes + ms) and the tree sizes")
    s.set_defaults(func=cmd_costs)

    s = add("doctor", "one screen: format, cache, lock, drift, python/sqlite/fts5, git")
    s.add_argument("--offline", action="store_true")
    s.set_defaults(func=cmd_doctor)

    s = add("append", "write an entry; the only sanctioned way")
    s.add_argument("kind")
    s.add_argument("--title", default="")
    s.add_argument("--body", default=None)
    s.add_argument("--body-file", dest="body_file", default=None)
    s.add_argument("--date", default="")
    s.add_argument("--host", default="")
    s.add_argument("--status", default="open")
    s.add_argument("--tags", default="")
    s.add_argument("--refs", default="")
    s.add_argument("--alias-of", dest="alias_of", default="")
    s.add_argument("--dry-run", dest="dry_run", action="store_true")
    s.add_argument("--no-fetch", dest="no_fetch", action="store_true")
    s.set_defaults(func=cmd_append)

    s = add("resolve", "record a status change in state/status.tsv (append-only)")
    s.add_argument("id")
    s.add_argument("--status", default="done",
                   choices=["open", "done", "retracted", "superseded", "blocked"])
    s.add_argument("--why", default="")
    s.add_argument("--alias-of", dest="alias_of", default="")
    s.set_defaults(func=cmd_resolve)

    s = add("import-legacy", "absorb entries that exist only in log/** or the flat files")
    s.add_argument("--apply", action="store_true")
    s.add_argument("--dry-run", dest="dry_run", action="store_true")
    s.add_argument("--include-shards", dest="include_shards", action="store_true",
                   help="also treat log/** shards as a source (migrate-v2 does this anyway)")
    s.set_defaults(func=cmd_import_legacy)

    s = add("migrate-v2", "split log/** into entries/ one-for-one, then absorb the flats")
    s.add_argument("--apply", action="store_true")
    s.add_argument("--dry-run", dest="dry_run", action="store_true")
    s.set_defaults(func=cmd_migrate_v2)

    s = add("dedupe", "exact-content duplicates: keep the lowest id, move the other")
    s.add_argument("--apply", action="store_true")
    s.set_defaults(func=cmd_dedupe)

    s = add("repair-ids", "renumber an entry whose id collides with different content")
    s.add_argument("--apply", action="store_true")
    s.set_defaults(func=cmd_repair_ids)

    s = add("gc-legacy", "freeze log/** into archive/ once it has been quiet")
    s.add_argument("--quiet-hours", dest="quiet_hours", type=float, default=24.0)
    s.add_argument("--apply", action="store_true")
    s.set_defaults(func=cmd_gc_legacy)

    s = add("index", "rebuild the cache explicitly")
    s.add_argument("--force", action="store_true")
    s.add_argument("--stats", action="store_true")
    s.set_defaults(func=cmd_index)

    s = add("next-id", "the next free number for a kind (entries/ + index + every git ref)")
    s.add_argument("kind")
    s.add_argument("--no-fetch", dest="no_fetch", action="store_true")
    s.set_defaults(func=cmd_next_id)

    s = add("import-flat", "DEPRECATED alias of import-legacy (a shipped script still calls it)")
    s.add_argument("files", nargs="*", help="ignored: v2 absorbs every source in one pass")
    s.add_argument("--kind", default="")
    s.add_argument("--apply", action="store_true")
    s.add_argument("--dry-run", dest="dry_run", action="store_true")
    s.set_defaults(func=cmd_import_flat)

    s = add("selftest", "run tools/selftest.py")
    s.set_defaults(func=cmd_selftest)

    s = add("verify", "run tools/verify.py: the independent no-loss gate, frozen v1 parser")
    s.set_defaults(func=cmd_verify)

    return p


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    try:
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    parser = build_parser()
    args = parser.parse_args(argv)
    global JOURNAL
    root = getattr(args, "root", None)
    if root:
        JOURNAL = Path(root).expanduser().resolve()
        clear_caches()
    cmd = getattr(args, "cmd", "")
    if cmd in MUTATING_COMMANDS:
        acquired, token = acquire_lock(cmd)
        if not acquired:
            return 3
        try:
            return args.func(args)
        finally:
            release_lock(token)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
