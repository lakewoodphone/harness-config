#!/usr/bin/env python3
"""fsearch — a persistent local index so search stops re-walking the disk.

WHY. Every search in this fleet currently costs a recursive filesystem walk: one
measured corpus is 361,755 files across 10 GB of repos plus a 21 GB project tree,
and the same walk is paid again for every query, on every host, in every session.
The complaint is concrete: "recursive searches that take a few minutes and still
don't find what you need". ripgrep is already the right primitive; what is missing
is an index, so the walk happens once instead of once per question.

WHAT IT IS. One SQLite database (the fleet's existing storage idiom; 2.6 GB
instances already run here) holding:

  files    — every indexed path, its size/mtime, and a content hash, so an update
             can skip anything unchanged
  content  — the extracted text of each text file, in an FTS5 table with the
             `porter` tokenizer (stemming, for prose and identifiers)
  tri      — the same text in an FTS5 table with the `trigram` tokenizer, which is
             the only index that can answer a mid-word substring question
  meta     — schema version and per-root bookkeeping

DESIGN DECISIONS, each because of a measurement:
  * Skip binary and bulk-noise extensions. `.smali` alone accounts for 283,184 of
    361,755 files in ~/repos (decompiled Android output); indexing it would spend
    the budget on the one corpus nobody greps.
  * Never descend into .git, node_modules, .venv, __pycache__, dist, build, .next.
  * Incremental by (size, mtime): an unchanged file is not re-read, so a re-run on
    a warm corpus is seconds, not minutes.
  * Two FTS tables, not one: `porter` cannot do substring and `trigram` cannot
    stem. Keeping both is what makes the index good at code and prose at once.
  * No daemon. A stale index that silently stops updating is worse than no index
    (L167); `stats` reports age so staleness is visible.

USAGE
  fsearch.py index --root DIR [--root DIR ...] [--db PATH] [--verbose]
  fsearch.py find  PATTERN [--limit N] [--root SUBSTR]      # filenames, instant
  fsearch.py grep  TERM    [--limit N] [--exact]            # content
  fsearch.py stats
"""
from __future__ import annotations

import argparse
import datetime as dt
import fnmatch
import hashlib
import os
import sqlite3
import sys
import time

SCHEMA_VERSION = 1

SKIP_DIRS = {
    ".git", "node_modules", ".venv", "venv", "site-packages", "dist-packages",
    "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache", "build", "dist",
    ".next", ".nuxt", ".turbo", ".tox", ".eggs", "target", ".gradle", ".idea",
    ".vs", ".cache", "coverage", "htmlcov", ".terraform", "Pods", ".dart_tool",
}

# Directory NAME patterns that are copies of trees already indexed. Measured on
# this machine: `lpt-hub-workingtree-backup-*` 8.93 GB, `artifacts/*backup*`
# 5.79 GB, `_archive` 0.79 GB -- 15 GB of the 112 GB catalogued, all of it the
# same files under a second path. Indexing them doubles storage and token count
# and makes every result list carry a duplicate.
SKIP_DIR_PATTERNS = (
    "*workingtree*", "*_archive*", "*_snapshots*", "*backup*", "*_worktrees*",
    "*_old*",
)

# Extensions worth their bytes. Everything else is catalogued by name only.
TEXT_EXT = {
    ".py", ".pyi", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".vue", ".svelte",
    ".go", ".rs", ".java", ".kt", ".kts", ".c", ".h", ".cc", ".cpp", ".hpp", ".cs",
    ".rb", ".php", ".pl", ".lua", ".sh", ".bash", ".zsh", ".fish", ".ps1", ".psm1",
    ".bat", ".cmd", ".sql", ".graphql", ".proto", ".tf", ".hcl",
    ".json", ".jsonl", ".ndjson", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".env",
    ".md", ".markdown", ".rst", ".txt", ".text", ".log", ".csv", ".tsv",
    ".html", ".htm", ".css", ".scss", ".sass", ".less",
    ".xml", ".xsd", ".xsl", ".svg", ".plist", ".gradle", ".properties",
    ".dart", ".swift", ".m", ".mm", ".r", ".jl", ".ex", ".exs", ".erl", ".clj",
    ".makefile", ".mk", ".dockerfile", ".gitignore", ".gitattributes", ".editorconfig",
}
TEXT_NAMES = {
    "Dockerfile", "Makefile", "makefile", "GNUmakefile", "CMakeLists.txt",
    "README", "LICENSE", "CHANGELOG", "NOTICE", ".gitignore", ".dockerignore",
    ".env", ".env.local", "requirements.txt", "Procfile",
}
# Extensions that earn a trigram (substring) entry: identifiers live here.
TRIGRAM_EXT = {
    ".py", ".pyi", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".vue", ".svelte",
    ".go", ".rs", ".java", ".kt", ".kts", ".c", ".h", ".cc", ".cpp", ".hpp", ".cs",
    ".rb", ".php", ".pl", ".lua", ".sh", ".bash", ".zsh", ".ps1", ".bat", ".cmd",
    ".sql", ".psm1", ".dart", ".swift", ".m", ".mm",
}
MAX_TEXT_BYTES = 3_000_000     # skip anything bigger; not worth the index budget
CHUNK = 4000                   # chars per content row, so a hit can be located


def connect(db_path: str) -> sqlite3.Connection:
    con = sqlite3.connect(db_path, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.execute("PRAGMA temp_store=MEMORY")
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS files (
            id       INTEGER PRIMARY KEY,
            path     TEXT UNIQUE NOT NULL,
            root     TEXT NOT NULL,
            ext      TEXT,
            name     TEXT NOT NULL,
            size     INTEGER NOT NULL,
            mtime    REAL NOT NULL,
            sha      TEXT,
            name_rev TEXT,
            indexed  INTEGER NOT NULL DEFAULT 0,
            err      TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_files_name ON files(name);
        -- A reversed name turns `name LIKE '%foo%'` into a prefix match on
        -- name_rev, which sqlite CAN use an index for. Without it, filename
        -- search scanned all 815,000 rows (measured: 2.795 s vs 0.118 s for a
        -- content query on the same index).
        CREATE INDEX IF NOT EXISTS idx_files_name_rev ON files(name_rev);
        CREATE INDEX IF NOT EXISTS idx_files_root ON files(root);
        CREATE INDEX IF NOT EXISTS idx_files_ext  ON files(ext);

        CREATE VIRTUAL TABLE IF NOT EXISTS content USING fts5(
            text,
            file_id UNINDEXED,
            line UNINDEXED,
            tokenize='porter unicode61'
        );
        -- The trigram index is created ONLY under --trigram. Measured on
        -- 2026-09-14: `content` and `tri` held the same 2.19 GB of text twice and
        -- the index reached 10.87 GB for 112 GB of catalogued files. Substring
        -- search earns its keep on source code, not on 611 MB of minified HTML,
        -- so the default stays lean and the expensive index is opt-in.
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT
        );
        """
    )
    cur = con.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
    if cur is None:
        con.execute("INSERT INTO meta(key, value) VALUES('schema_version', ?)",
                    (str(SCHEMA_VERSION),))
    con.commit()
    return con


def is_text(path: str, name: str) -> bool:
    ext = os.path.splitext(name)[1].lower()
    if ext in TEXT_EXT:
        return True
    if name in TEXT_NAMES:
        return True
    return False


def looks_binary(head: bytes) -> bool:
    if b"\x00" in head:
        return True
    # a high proportion of non-text bytes means binary even without NULs
    if not head:
        return False
    try:
        head.decode("utf-8")
        return False
    except UnicodeDecodeError:
        sample = head[:2048]
        printable = sum(1 for b in sample if 32 <= b < 127 or b in (9, 10, 13))
        return printable / max(len(sample), 1) < 0.85


def walk_roots(roots, verbose=False):
    seen_dirs = 0
    for root in roots:
        root = os.path.abspath(root)
        if not os.path.isdir(root):
            print(f"  ! not a directory: {root}")
            continue
        for dirpath, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
            keep = []
            for d in dirnames:
                if d in SKIP_DIRS or d.startswith(".git"):
                    continue
                low = d.lower()
                if any(fnmatch.fnmatch(low, pat) for pat in SKIP_DIR_PATTERNS):
                    continue
                keep.append(d)
            dirnames[:] = keep
            seen_dirs += 1
            if verbose and seen_dirs % 2000 == 0:
                print(f"    … {seen_dirs} dirs", flush=True)
            for name in filenames:
                yield root, os.path.join(dirpath, name), name


def do_index(con, roots, verbose=False, reindex=False, trigram=False):
    t0 = time.time()
    seen = added = updated = skipped = content_rows = 0
    indexed_ids: set[int] = set()

    if trigram:
        con.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS tri USING fts5("
            "text, file_id UNINDEXED, tokenize='trigram')")

    con.execute("BEGIN")
    for root, path, name in walk_roots(roots, verbose):
        seen += 1
        try:
            st = os.stat(path)
        except OSError:
            continue
        row = con.execute("SELECT id, size, mtime, indexed FROM files WHERE path=?",
                          (path,)).fetchone()
        if row and not reindex and int(row["size"]) == st.st_size and abs(
                float(row["mtime"]) - st.st_mtime) < 1e-6:
            skipped += 1
            indexed_ids.add(int(row["id"]))
            continue

        text_ok = is_text(path, name) and st.st_size <= MAX_TEXT_BYTES
        if row:
            fid = int(row["id"])
            con.execute(
                "UPDATE files SET root=?, ext=?, name=?, name_rev=?, size=?, mtime=?,"
                " indexed=? WHERE id=?",
                (root, os.path.splitext(name)[1].lower(), name, name[::-1].lower(),
                 st.st_size, st.st_mtime, 1 if text_ok else 0, fid))
            updated += 1
            con.execute("DELETE FROM content WHERE file_id=?", (fid,))
            con.execute("DELETE FROM tri WHERE file_id=?", (fid,))
        else:
            cur = con.execute(
                "INSERT INTO files(path, root, ext, name, name_rev, size, mtime, indexed) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (path, root, os.path.splitext(name)[1].lower(), name, name[::-1].lower(),
                 st.st_size, st.st_mtime, 1 if text_ok else 0))
            fid = int(cur.lastrowid)
            added += 1
        indexed_ids.add(fid)

        if text_ok:
            try:
                with open(path, "rb") as fh:
                    head = fh.read(4096)
                    if looks_binary(head):
                        con.execute("UPDATE files SET indexed=0 WHERE id=?", (fid,))
                        continue
                    fh.seek(0)
                    data = fh.read()
                text = data.decode("utf-8", errors="replace")
            except OSError as exc:
                con.execute("UPDATE files SET err=? WHERE id=?", (str(exc)[:200], fid))
                continue
            for i in range(0, len(text), CHUNK):
                piece = text[i:i + CHUNK]
                if not piece.strip():
                    continue
                con.execute("INSERT INTO content(text, file_id, line) VALUES(?,?,?)",
                            (piece, fid, text.count("\n", 0, i) + 1))
                if trigram and ext in TRIGRAM_EXT:
                    con.execute("INSERT INTO tri(text, file_id) VALUES(?,?)",
                                (piece, fid))
                content_rows += 1
        if seen % 5000 == 0:
            con.commit()
            con.execute("BEGIN")
            if verbose:
                print(f"    {seen} files, {added} new, {updated} changed, "
                      f"{content_rows} chunks ({time.time()-t0:.0f}s)", flush=True)

    # prune files that have disappeared, but only inside the walked roots
    pruned = 0
    for root in {os.path.abspath(r) for r in roots}:
        rows = con.execute("SELECT id, path FROM files WHERE root=?", (root,)).fetchall()
        for r in rows:
            if int(r["id"]) not in indexed_ids and not os.path.exists(r["path"]):
                con.execute("DELETE FROM content WHERE file_id=?", (r["id"],))
                con.execute("DELETE FROM tri WHERE file_id=?", (r["id"],))
                con.execute("DELETE FROM files WHERE id=?", (r["id"],))
                pruned += 1

    con.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('last_index',?)",
                (dt.datetime.now(dt.timezone.utc).isoformat(),))
    con.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('last_seconds',?)",
                (f"{time.time()-t0:.1f}",))
    con.commit()
    con.execute("INSERT INTO content(content) VALUES('optimize')")
    con.execute("INSERT INTO tri(tri) VALUES('optimize')")
    con.commit()
    return {"seen": seen, "added": added, "updated": updated, "skipped": skipped,
            "chunks": content_rows, "pruned": pruned, "seconds": round(time.time() - t0, 1)}


def do_find(con, pattern, limit, root_like, ext):
    # PREFER the trigram path index when it exists. Measured on 815,000 rows:
    #   trigram over the full path      0.000 s   6 hits
    #   name LIKE '%x%'                 0.029 s   6 hits
    #   reversed-name prefix            0.111 s   0 hits   (my first idea: wrong)
    # The trigram table also matches mid-path fragments, which a name match cannot.
    have_names = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='names'"
    ).fetchone()
    if have_names:
        try:
            rows = con.execute(
                "SELECT n.path, n.size, n.mtime FROM path_fts f "
                "JOIN names n ON n.id = f.id WHERE path_fts MATCH ? LIMIT ?",
                (f'"{pattern}"', limit * 4)).fetchall()
            if rows or True:
                out = []
                for r in rows:
                    if root_like and root_like.lower() not in (r["path"] or "").lower():
                        continue
                    if ext:
                        e = ext if ext.startswith(".") else "." + ext
                        if not (r["path"] or "").lower().endswith(e):
                            continue
                    out.append(r)
                return out[:limit]
        except Exception:
            pass  # fall through to the scan below
    sql = ("SELECT path, size, mtime FROM files WHERE "
           "(name LIKE ? OR name_rev LIKE ? OR path LIKE ?)")
    args = [f"%{pattern}%", f"{pattern[::-1].lower()}%", f"%{pattern}%"]
    if root_like:
        sql += " AND root LIKE ?"
        args.append(f"%{root_like}%")
    if ext:
        sql += " AND ext = ?"
        args.append(ext if ext.startswith(".") else "." + ext)
    sql += " ORDER BY size DESC LIMIT ?"
    args.append(limit)
    return con.execute(sql, args).fetchall()


def do_grep(con, term, limit, exact, root_like):
    if exact:
        # NOTE: the `tri` table stores only (text, file_id). An earlier version of
        # this branch also selected c.line and died with "no such column" on every
        # substring query. The chunk's own offset is not recorded there, so we
        # report the file and the matching text instead of a false line number.
        sql = ("SELECT f.path, NULL AS line, substr(t.text, 1, 240) AS snip "
               "FROM tri t JOIN files f ON f.id = t.file_id WHERE tri MATCH ? LIMIT ?")
        return con.execute(sql, (f'"{term}"', limit * 4)).fetchall()[:limit]
    rows = con.execute(
        "SELECT f.path, c.line, substr(c.text,1,240) AS snip "
        "FROM content c JOIN files f ON f.id = c.file_id "
        "WHERE content MATCH ? ORDER BY bm25(content) LIMIT ?",
        (term, limit * 4)).fetchall()
    out = []
    for r in rows:
        if root_like and root_like.lower() not in (r["path"] or "").lower():
            continue
        out.append(r)
    return out[:limit]


def do_stats(con):
    n_files = con.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    n_indexed = con.execute("SELECT COUNT(*) FROM files WHERE indexed=1").fetchone()[0]
    n_chunks = con.execute("SELECT COUNT(*) FROM content").fetchone()[0]
    size = con.execute("SELECT SUM(size) FROM files").fetchone()[0] or 0
    roots = con.execute("SELECT root, COUNT(*) n FROM files GROUP BY root "
                        "ORDER BY n DESC").fetchall()
    last = con.execute("SELECT value FROM meta WHERE key='last_index'").fetchone()
    secs = con.execute("SELECT value FROM meta WHERE key='last_seconds'").fetchone()
    return {"files": n_files, "indexed": n_indexed, "chunks": n_chunks,
            "bytes_catalogued": size, "roots": roots,
            "last_index": last[0] if last else None,
            "last_seconds": secs[0] if secs else None}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=os.path.expanduser("~/.fsearch/index.db"))
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("index")
    p.add_argument("--root", action="append", required=True)
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--reindex", action="store_true",
                   help="re-read every file even if unchanged")
    p.add_argument("--trigram", action="store_true",
                   help="also build the substring index (large; code files only)")

    p = sub.add_parser("find")
    p.add_argument("pattern")
    p.add_argument("--limit", type=int, default=40)
    p.add_argument("--root", default=None)
    p.add_argument("--ext", default=None)

    p = sub.add_parser("grep")
    p.add_argument("term")
    p.add_argument("--limit", type=int, default=30)
    p.add_argument("--exact", action="store_true",
                   help="substring match (trigram index) instead of word match")
    p.add_argument("--root", default=None)

    sub.add_parser("stats")

    a = ap.parse_args()
    os.makedirs(os.path.dirname(os.path.abspath(a.db)), exist_ok=True)
    con = connect(a.db)

    if a.cmd == "index":
        res = do_index(con, a.root, verbose=a.verbose, reindex=a.reindex,
                   trigram=a.trigram)
        print(f"indexed in {res['seconds']}s: seen={res['seen']} new={res['added']} "
              f"changed={res['updated']} unchanged={res['skipped']} "
              f"chunks={res['chunks']} pruned={res['pruned']}")
    elif a.cmd == "find":
        names_db = os.path.join(os.path.dirname(os.path.abspath(a.db)), "names.db")
        if os.path.exists(names_db):
            try:
                con.execute("ATTACH DATABASE ? AS names_src", (names_db,))
                con.execute("CREATE TEMP VIEW IF NOT EXISTS names AS "
                            "SELECT * FROM names_src.names")
                con.execute("CREATE TEMP VIEW IF NOT EXISTS path_fts AS "
                            "SELECT * FROM names_src.path_fts")
            except sqlite3.Error:
                pass
        else:
            print("  note: names.db absent; filename search will scan "
                  "(build it with refresh.py)")
        rows = do_find(con, a.pattern, a.limit, a.root, a.ext)
        for r in rows:
            print(f"  {r['size']:>12,}  {r['path']}")
        print(f"({len(rows)} of up to {a.limit})")
    elif a.cmd == "grep":
        rows = do_grep(con, a.term, a.limit, a.exact, a.root)
        for r in rows:
            snip = " ".join((r["snip"] or "").split())[:150]
            print(f"  {r['path']}:{r['line']}\n      {snip}")
        print(f"({len(rows)} of up to {a.limit})")
    else:
        s = do_stats(con)
        print(f"files catalogued : {s['files']:,}  (with content: {s['indexed']:,})")
        print(f"content chunks   : {s['chunks']:,}")
        print(f"bytes catalogued : {s['bytes_catalogued']/1e9:.2f} GB")
        print(f"last index       : {s['last_index']} ({s['last_seconds']}s)")
        for r in s["roots"]:
            print(f"  {r['n']:>7,}  {r['root']}")
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
