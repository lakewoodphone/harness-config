"""De-duplicate the file index by case, fast, using NOCASE instead of row-by-row.

WHY NOT THE OBVIOUS WAY. My first attempt updated path_key per row and then deleted
duplicates one at a time. On 1.84 million rows that is minutes of individual
statements -- it ran 1,016 s of CPU without finishing, and I killed it. SQLite
already has the right tool: a UNIQUE index with COLLATE NOCASE, which collapses
`Code\\x` and `code\\x` at the engine level.

This reshapes the table once, in bulk, and reports the real numbers.
"""
import os
import sqlite3
import time

F = os.path.join(os.path.expanduser("~"), ".fsearch")
DB = os.path.join(F, "index.db")

con = sqlite3.connect(DB, timeout=120)
con.row_factory = sqlite3.Row
con.execute("PRAGMA journal_mode=WAL")
con.execute("PRAGMA synchronous=OFF")
con.execute("PRAGMA temp_store=MEMORY")
con.execute("PRAGMA cache_size=-200000")          # ~200 MB page cache

t0 = time.time()
before = con.execute("SELECT COUNT(*) FROM files").fetchone()[0]
print(f"files before: {before:,}")

# How many are case-duplicates of each other?
dupes = con.execute("""
    SELECT COUNT(*) FROM (
      SELECT LOWER(path) p FROM files GROUP BY p HAVING COUNT(*) > 1)
""").fetchone()[0]
print(f"case-duplicate path groups: {dupes:,}")

cols = [r[1] for r in con.execute("PRAGMA table_info(files)")]
print("columns:", ", ".join(cols))

# Rebuild with a NOCASE unique key, keeping the first row per case-folded path.
con.executescript("""
    CREATE TABLE files_new AS
    SELECT * FROM files LIMIT 0;
""")
con.execute("""
    INSERT INTO files_new(id, path, root, ext, name, size, mtime, sha, name_rev,
                          indexed, err, path_key)
    SELECT id, path, root, ext, name, size, mtime, sha, name_rev,
           indexed, err, LOWER(path)
    FROM files
    GROUP BY LOWER(path)
    HAVING id = MIN(id)
""")
con.commit()
after = con.execute("SELECT COUNT(*) FROM files_new").fetchone()[0]
print(f"files after : {after:,}   removed {before - after:,} duplicates "
      f"({100.0 * (before - after) / max(before, 1):.1f}%)")

# Only drop content rows whose file no longer exists.
removed = con.execute("""
    DELETE FROM content WHERE file_id NOT IN (SELECT id FROM files_new)
""").rowcount
con.commit()
print(f"content chunks removed with the duplicates: {removed:,}")

con.executescript("""
    DROP TABLE files;
    ALTER TABLE files_new RENAME TO files;
    CREATE INDEX idx_files_name ON files(name);
    CREATE INDEX idx_files_name_rev ON files(name_rev);
    CREATE INDEX idx_files_root ON files(root);
    CREATE INDEX idx_files_ext  ON files(ext);
    CREATE UNIQUE INDEX idx_files_path_nocase ON files(path COLLATE NOCASE);
""")
con.commit()
print(f"done in {time.time() - t0:.1f}s")
con.close()
