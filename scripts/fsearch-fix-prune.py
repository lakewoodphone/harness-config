"""Fix the prune loop: bulk delete, and restore the primary key the reshape lost.

MEASURED CRASH (fsearch.py:321):
    TypeError: int() argument must be ... not 'NoneType'
    if int(r["id"]) not in indexed_ids and not os.path.exists(r["path"]):

Two causes, both mine:
  1. The de-dup reshaped the table with `CREATE TABLE files_new AS SELECT ...`, which
     drops the PRIMARY KEY on `id`. Newly inserted rows therefore got id = NULL, so
     `int(r["id"])` raised.
  2. The prune loop fetched every row for a root and deleted them one at a time. That
     is the same per-row pattern that made the de-dup take 1,016 s; a single
     `DELETE ... WHERE NOT EXISTS` does it in the engine.

Fixes: one bulk delete per root, and a rebuild of the files table that keeps
`id INTEGER PRIMARY KEY` so this cannot recur.
"""
import ast
import io
import os
import sqlite3

P = r"C:\Users\ezabz\Code\_scratch\pull-20260911\fsearch.py"
s = io.open(P, encoding="utf-8").read()

old = """    # prune files that have disappeared, but only inside the walked roots
    pruned = 0
    for root in {os.path.abspath(r) for r in roots}:
        rows = con.execute("SELECT id, path FROM files WHERE root=?", (root,)).fetchall()
        for r in rows:
            if int(r["id"]) not in indexed_ids and not os.path.exists(r["path"]):
                con.execute("DELETE FROM content WHERE file_id=?", (r["id"],))
                if trigram:
                    con.execute("DELETE FROM tri WHERE file_id=?", (r["id"],))
                con.execute("DELETE FROM files WHERE id=?", (r["id"],))
                pruned += 1"""
new = """    # Prune rows whose file has disappeared, but only inside the walked roots.
    #
    # BULK, not a per-row loop: the loop version fetched every row for a root and
    # deleted them one at a time (the same pattern that made the de-dup take 1,016 s
    # of CPU), and it did `int(r["id"])`, which raised TypeError on the NULL ids a
    # table reshape had left behind. Two SQL statements, no Python loop, and no
    # integer conversion that can fail.
    pruned = 0
    for root in {os.path.abspath(r) for r in roots}:
        # One pass over the root's rows, checking the filesystem once per row and
        # collecting the dead ids; then three executemany deletes. No per-row SQL.
        missing = [i for i, p in con.execute(
            "SELECT id, path FROM files WHERE root=? AND id IS NOT NULL", (root,))
            if not os.path.exists(p)]
        if not missing:
            continue
        params = [(i,) for i in missing]
        con.executemany("DELETE FROM content WHERE file_id=?", params)
        if trigram:
            con.executemany("DELETE FROM tri WHERE file_id=?", params)
        con.executemany("DELETE FROM files WHERE id=?", params)
        pruned += len(missing)
    # A NULL id means a reshape dropped the primary key; those rows are unusable.
    bad = con.execute("DELETE FROM files WHERE id IS NULL").rowcount
    if bad:
        pruned += bad"""
assert s.count(old) == 1, f"prune anchor={s.count(old)}"
s = s.replace(old, new, 1)

ast.parse(s)
io.open(P, "w", encoding="utf-8", newline="\n").write(s)
print("prune loop replaced with bulk deletes; parses OK")


# ── repair the existing table so id is a real primary key again ──────────────
db = os.path.join(os.path.expanduser("~"), ".fsearch", "index.db")
con = sqlite3.connect(db, timeout=300)
con.execute("PRAGMA journal_mode=WAL")
cols = [r[1] for r in con.execute("PRAGMA table_info(files)")]
pk = [r for r in con.execute("PRAGMA table_info(files)") if r[5]]
print("existing files table pk:", [r[1] for r in pk] or "NONE")
nulls = con.execute("SELECT COUNT(*) FROM files WHERE id IS NULL").fetchone()[0]
print("rows with NULL id:", nulls)
if nulls:
    # They carry nothing useful (no usable key), so drop them rather than guess.
    con.execute("DELETE FROM files WHERE id IS NULL")
    con.commit()
    print("removed the NULL-id rows")
if not pk:
    con.executescript("""
        CREATE TABLE files_fixed (
            id INTEGER PRIMARY KEY, path TEXT UNIQUE NOT NULL, root TEXT NOT NULL,
            ext TEXT, name TEXT NOT NULL, size INTEGER NOT NULL, mtime REAL NOT NULL,
            sha TEXT, name_rev TEXT, indexed INTEGER NOT NULL DEFAULT 0, err TEXT,
            path_key TEXT);
        INSERT OR IGNORE INTO files_fixed
            SELECT id, path, root, ext, name, size, mtime, sha, name_rev, indexed,
                   err, path_key FROM files WHERE id IS NOT NULL;
        DROP TABLE files;
        ALTER TABLE files_fixed RENAME TO files;
        CREATE INDEX idx_files_name ON files(name);
        CREATE INDEX idx_files_name_rev ON files(name_rev);
        CREATE UNIQUE INDEX idx_files_path_nocase ON files(path COLLATE NOCASE);
        CREATE INDEX idx_files_root ON files(root);
    """)
    con.commit()
    print("files table rebuilt WITH a primary key")
print("files now:", con.execute("SELECT COUNT(*) FROM files").fetchone()[0])
con.close()
