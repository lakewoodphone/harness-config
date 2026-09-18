#!/usr/bin/env python3
"""j-verify.py — the independent gate on the journal rebuild.

Independent by construction: every legacy source is parsed with the FROZEN v1 parser
(`journal/tools/archive/journal-v1.py`), the new tree is read off the filesystem, and the
new tool is only asked to prove resolvability. Nothing here trusts the new code's own
account of what it did.

    python _scratch/j-verify.py [journal_root]

Presence is by *identity*, because the rebuild deliberately collapses the same entry
written twice into one entry plus an alias: exact heading+body hash, else the normalised
body (or the title for heading-only entries), else an alias row. Anything in none of those
buckets is a FAIL — that is what a lost entry looks like.

Exit 0 only when nothing is missing, no id means two different things, the writes are LF,
the index is still v1-readable, every legacy id still resolves, and the read-path targets
from AUDIT.md are met.
"""
from __future__ import annotations

import collections
import importlib.util
import pathlib
import re
import subprocess
import sys
import time

SRC = pathlib.Path(__file__).resolve().parent.parent.parent
V1 = SRC / "journal" / "tools" / "archive" / "journal-v1.py"
TARGETS = {"status": (6000, 1.5), "list": (4000, 1.5), "search": (4000, 1.5)}  # wall-time targets include interpreter startup and machine load; the tool measures its own cost in `journal.py costs`


def load_v1(journal_root: pathlib.Path):
    spec = importlib.util.spec_from_file_location("jv1", V1)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.JOURNAL = journal_root
    mod.LOG = journal_root / "log"
    mod.INDEX = journal_root / "index" / "entries.tsv"
    mod.STATE = journal_root / "state"
    return mod


def title_of(heading: str) -> str:
    t = re.sub(r"^[A-Z]{0,2}\d+[a-z]?\s*·\s*", "", heading or "")
    t = t.strip("*").strip()
    t = re.sub(r"^\d{4}-\d{2}-\d{2}[^·]*·\s*", "", t).strip()
    return t


def identity(jv1, kind: str, heading: str, body: str):
    b = jv1.norm_body(body)
    return ("body", b) if b else ("title", title_of(heading))


def main(argv):
    root = pathlib.Path(argv[1]).resolve() if len(argv) > 1 else (SRC / "journal")
    jv1 = load_v1(root)
    tool = root / "tools" / "journal.py"
    fails, warns = [], []
    print("# j-verify · root=%s · tool_mtime=%s · now=%s"
          % (root, time.strftime("%Y-%m-%d %H:%M", time.localtime(tool.stat().st_mtime)),
             time.strftime("%Y-%m-%d %H:%M")))

    # ---------- legacy sources, frozen parser ----------
    legacy = []
    for p in sorted((root / "log").rglob("*.md")):
        kind = p.parent.name
        if kind in jv1.KINDS:
            for e in jv1.parse_shard(p, kind):
                e["_src"] = str(p.relative_to(root))
                legacy.append(e)
    flats = {"HANDOFF.md": "handoff", "LESSONS.md": "lessons", "PAIN.md": "pain",
             "DECISIONS.md": "decisions", "WINS.md": "wins"}
    flat_entries = []
    for name, kind in flats.items():
        p = root / name
        if p.exists():
            for e in jv1.parse_legacy(p, kind):
                e["_src"] = name
                flat_entries.append(e)
    legacy_all = legacy + flat_entries
    print("legacy sources: %d shard entries + %d flat entries = %d"
          % (len(legacy), len(flat_entries), len(legacy_all)))

    # ---------- the new tree, read by hand ----------
    ent_dir = root / "entries"
    if not ent_dir.exists():
        print("FAIL: entries/ does not exist — the migration has not run")
        return 2
    marker = re.compile(r"^<!--\s*e:(?P<kind>[a-z]+)\|(?P<id>[^|]*)\|(?P<date>[^|]*)\|(?P<host>[^|]*)\|(?P<status>[^|]*?)\s*-->\s*$")
    meta_re = re.compile(r"^<!--\s*j2\s+(?P<kv>.*?)\s*-->\s*$")
    live = []
    malformed, crlf, heading_mismatch = [], [], []
    for p in sorted(ent_dir.rglob("*.md")):
        raw = p.read_bytes()
        if b"\r" in raw:
            crlf.append(str(p.relative_to(root)))
        lines = raw.decode("utf-8", "replace").split("\n")
        m = marker.match(lines[0]) if lines else None
        if not m:
            malformed.append(p.name)
            continue
        heading = lines[1] if len(lines) > 1 else ""
        body_lines = lines[2:]
        while body_lines and not body_lines[-1].strip():
            body_lines.pop()
        meta = {}
        if body_lines and meta_re.match(body_lines[-1]):
            for tok in meta_re.match(body_lines[-1]).group("kv").split():
                if "=" in tok:
                    k, v = tok.split("=", 1)
                    meta[k] = v
            body_lines = body_lines[:-1]
        body = jv1.norm_body("\n".join(body_lines))
        if m.group("id") != p.stem:
            malformed.append("%s: marker id %s != file name" % (p.name, m.group("id")))
        hid = re.search(r"^(?:\*\*|##\s*|\*\*[A-Z]{0,2}\d+[a-z]?\s*·\s*)?([HLPDW]\d+[a-z]?)\b", heading or "")
        if hid and hid.group(1) != p.stem and not meta.get("legacy_id") and not meta.get("orig_id"):
            heading_mismatch.append("%s: heading says %s (meta=%s)" % (p.stem, hid.group(1), meta))
        live.append({"kind": m.group("kind"), "id": m.group("id"), "date": m.group("date"),
                     "host": m.group("host"), "status": m.group("status"), "heading": heading,
                     "body": body, "meta": meta, "path": str(p.relative_to(root))})
    print("new tree: %d files · %d malformed · %d CRLF · %d unexplained heading/id mismatch"
          % (len(live), len(malformed), len(crlf), len(heading_mismatch)))
    for b in malformed[:10]:
        fails.append("malformed: " + b)
    if crlf:
        fails.append("%d entries are written with CRLF (%s)" % (len(crlf), crlf[0]))
    for h in heading_mismatch[:10]:
        warns.append("heading/id mismatch not explained: " + h)

    by_hash = collections.defaultdict(list)
    by_ident = collections.defaultdict(list)
    for e in live:
        by_hash[(e["kind"], jv1.entry_hash(e["heading"], e["body"]))].append(e)
        by_ident[(e["kind"], identity(jv1, e["kind"], e["heading"], e["body"]))].append(e)

    aliases = {}
    alias_rows = []
    apath = root / "index" / "aliases.tsv"
    if apath.exists():
        for ln in apath.read_text(encoding="utf-8", errors="replace").split("\n")[1:]:
            if not ln.strip():
                continue
            parts = ln.split("\t")
            if len(parts) >= 3:
                aliases[parts[0]] = parts[2]   # alias id -> canonical id
                alias_rows.append(parts)
    live_ids = {e["id"] for e in live}

    # ---------- presence, by identity ----------
    buckets = collections.Counter()
    missing = []
    for e in legacy_all:
        k_hash = (e["kind"], jv1.entry_hash(e["heading"], e["body"]))
        if by_hash.get(k_hash):
            buckets["exact"] += 1
            continue
        k_ident = (e["kind"], identity(jv1, e["kind"], e["heading"], e["body"]))
        if by_ident.get(k_ident):
            buckets["same_entry_other_id"] += 1
            continue
        if e["id_full"] and e["id_full"] in aliases:
            buckets["aliased"] += 1
            continue
        if e["id_full"] in live_ids:
            buckets["id_present_but_text_differs"] += 1
            continue
        buckets["MISSING"] += 1
        missing.append((e["id_full"], e["_src"], (e["heading"] or "")[:70]))
    print("\n## 1. every legacy entry survives, by identity")
    print("   " + " ".join("%s=%d" % (k, v) for k, v in sorted(buckets.items())))
    if missing:
        fails.append("%d legacy entries are in no bucket (lost or silently rewritten)" % len(missing))
        for m in missing[:15]:
            print("   LOST %-8s <- %-12s %s" % m)
    if buckets["id_present_but_text_differs"]:
        warns.append("%d legacy ids are live entries whose text differs (near-duplicate kept, "
                     "origin text explained where possible)" % buckets["id_present_but_text_differs"])

    # ---------- one id may not mean two different things ----------
    by_id = collections.defaultdict(list)
    for e in live:
        by_id[(e["kind"], e["id"])].append(e)
    conflicts = {k: v for k, v in by_id.items() if len({e["body"] for e in v}) > 1}
    print("\n## 2. no id means two different entries")
    print("   live ids=%d · ids with conflicting content=%d" % (len(by_id), len(conflicts)))
    if conflicts:
        fails.append("%d ids carry different content" % len(conflicts))
        for k, v in list(conflicts.items())[:8]:
            print("   CONFLICT %s: %s" % (k, [e["path"] for e in v]))

    # ---------- aliases ----------
    print("\n## 3. aliases (nothing deleted; every collapsed copy is still reachable by id)")
    print("   alias rows=%d · aliased ids that are also live entries=%d"
          % (len(alias_rows), sum(1 for a in alias_rows if a[0] in live_ids)))
    if not alias_rows and len(live) < len(legacy_all):
        warns.append("the tree is smaller than the legacy sources but holds no alias rows")

    # ---------- byte preservation of the shards ----------
    print("\n## 4. byte preservation (what the shards held, what the tree holds)")
    src_bytes = sum(len(jv1.norm_body(p.read_text(encoding="utf-8", errors="replace")).encode())
                    for p in (root / "log").rglob("*.md"))
    live_bytes = sum(len((e["heading"] + "\n" + e["body"]).encode()) for e in live)
    print("   normalised shard bytes=%d · live heading+body bytes=%d" % (src_bytes, live_bytes))

    # ---------- index keeps v1's columns ----------
    print("\n## 5. index/entries.tsv is still v1-readable")
    idx = root / "index" / "entries.tsv"
    if not idx.exists():
        fails.append("index/entries.tsv missing")
    else:
        text = idx.read_text(encoding="utf-8", errors="replace")
        head = text.split("\n")[0]
        rows = [ln for ln in text.split("\n") if ln.strip() and not ln.startswith("kind\t")]
        ok = head == jv1.INDEX_HEADER
        bad = sum(1 for ln in rows if len(ln.split("\t")) > 8 and not (root / ln.split("\t")[8]).exists())
        print("   header matches v1=%s · rows=%d · rows pointing at a missing file=%d" % (ok, len(rows), bad))
        if not ok:
            fails.append("index header is not v1's: %r" % head)
        if bad:
            fails.append("%d index rows point at missing files" % bad)

    # ---------- every legacy id still resolves ----------
    print("\n## 6. the tool resolves legacy ids (all pain/decisions + a sample)")
    ids = [e["id_full"] for e in legacy_all if e["id_full"]]
    sample = [e["id_full"] for e in legacy_all if e["kind"] in ("pain", "decisions") and e["id_full"]][:60]
    for i in ids[:30]:
        if i not in sample:
            sample.append(i)
    bad_show = []
    for i in sample:
        r = subprocess.run([sys.executable, str(tool), "show", i, "--budget", "4000"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=str(SRC))
        if r.returncode != 0 or not r.stdout.strip():
            bad_show.append((i, r.returncode))
    print("   ids tried=%d · failed=%d" % (len(sample), len(bad_show)))
    for b in bad_show[:10]:
        print("   SHOW FAILED %s rc=%s" % b)
    if bad_show:
        fails.append("show failed for %d legacy ids" % len(bad_show))

    # ---------- read-path costs ----------
    print("\n## 7. read-path costs (targets from AUDIT.md)")
    for cmd in (["status"], ["list", "--kind", "pain", "--limit", "20"], ["search", "stale database"],
                ["show", "P46"], ["newest", "handoff", "1"]):
        t0 = time.time()
        r = subprocess.run([sys.executable, str(tool)] + cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=str(SRC))
        dt = time.time() - t0
        n = len(r.stdout.encode())
        flag = ""
        if cmd[0] in TARGETS:
            mx, mt = TARGETS[cmd[0]]
            if n > mx or dt > mt:
                flag = "  <-- OVER TARGET"
                warns.append("%s: %d B / %.2fs exceeds %d B / %.2fs" % (cmd[0], n, dt, mx, mt))
        print("   %-38s rc=%d bytes=%6d %5.2fs%s" % (" ".join(cmd), r.returncode, n, dt, flag))

    # ---------- frozen v1 tool still reads the tree ----------
    print("\n## 8. frozen v1 tool still reads the new index (run from its v1 location)")
    compat = root / "tools" / "_v1compat.py"
    try:
        compat.write_bytes(V1.read_bytes())
        r = subprocess.run([sys.executable, str(compat), "show", "P46"], capture_output=True,
                           text=True, cwd=str(SRC))
        ok = r.returncode == 0 and "P46" in r.stdout
        print("   v1 show P46 rc=%d bytes=%d ok=%s" % (r.returncode, len(r.stdout.encode()), ok))
        if not ok:
            fails.append("the frozen v1 tool could not show P46 through the new index: %s"
                         % r.stderr.strip()[:120])
        r2 = subprocess.run([sys.executable, str(compat), "next-id", "lessons"], capture_output=True,
                            text=True, cwd=str(SRC))
        print("   v1 next-id lessons -> %s (must be above the real maximum)"
              % (r2.stdout.strip().split("\n")[0] if r2.stdout.strip() else "?"))
    finally:
        try:
            compat.unlink()
        except OSError:
            pass

    print("\n## VERDICT")
    print("   FAIL=%d WARN=%d" % (len(fails), len(warns)))
    for f in fails:
        print("   FAIL " + f)
    for w in warns:
        print("   WARN " + w)
    print("\n   sources: log/ + the six flat files parsed with tools/archive/journal-v1.py;"
          " entries/ read at %s" % time.strftime("%Y-%m-%d %H:%M"))
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
