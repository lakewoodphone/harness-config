"""Give chatindex explicit transaction control, which is what it always assumed.

ROOT CAUSE of a defect that has now cost three runs and emptied a working index:

    sqlite3.OperationalError: cannot start a transaction within a transaction

Python's sqlite3 module opens an IMPLICIT transaction on the first INSERT/UPDATE
when isolation_level is left at its default. chatindex then called
`con.execute("BEGIN")` explicitly in the emit loop, which SQLite refuses while a
transaction is already open. Every file with content raised, the `except` in
do_index printed `! <file>` and moved on, and because the version-mismatch path had
already DELETED that file's rows, the end state was an index with 21,951 FTS rows and
ZERO messages -- every session reported as `ok`, because the quality flag is set
from the parse, not from the write.

I had already "fixed" this twice by wrapping BEGIN in try/except, which silenced the
symptom at one call site and left the other. The correct fix is to set
`isolation_level = None` so the module stops injecting transactions and every
BEGIN/COMMIT in this file means exactly what it says.
"""
import ast
import io
import os
import shutil
import sqlite3
import time

P = r"C:\Users\ezabz\Code\_scratch\pull-20260911\chatindex2.py"
s = io.open(P, encoding="utf-8").read()

# 1. take transaction control away from the driver
old = '''    con = sqlite3.connect(db_path, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")'''
new = '''    con = sqlite3.connect(db_path, timeout=30)
    # Python's sqlite3 opens an implicit transaction on the first write unless this
    # is set, which makes an explicit "BEGIN" raise "cannot start a transaction
    # within a transaction". Setting isolation_level=None (autocommit) hands
    # transaction control to this file, where every BEGIN/COMMIT is deliberate.
    con.isolation_level = None
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")'''
assert s.count(old) == 1, f"connect anchor={s.count(old)}"
s = s.replace(old, new, 1)

# 2. guard the remaining explicit BEGINs so a stray open transaction cannot kill a
#    whole file, and so the failure is reported instead of swallowed
old2 = '''    # ── emit turns ──
    written = 0
    con.execute("BEGIN")'''
new2 = '''    # ── emit turns ──
    written = 0
    if con.in_transaction:
        con.commit()                 # never BEGIN inside an open transaction
    con.execute("BEGIN")'''
assert s.count(old2) == 1, f"emit anchor={s.count(old2)}"
s = s.replace(old2, new2, 1)

old3 = '''            try:
                con.execute("BEGIN")
            except sqlite3.OperationalError:
                pass'''
new3 = '''            if con.in_transaction:
                con.commit()
            con.execute("BEGIN")'''
assert s.count(old3) == 1, f"batch anchor={s.count(old3)}"
s = s.replace(old3, new3, 1)

# 3. a file that fails must be LOUD, not a quiet "!" line
old4 = '''        except (OSError, ValueError, sqlite3.Error) as exc:
            print(f"  ! {os.path.basename(path)}: {exc}")
            continue'''
new4 = '''        except (OSError, ValueError, sqlite3.Error) as exc:
            errors += 1
            print(f"  ! {os.path.basename(path)}: {type(exc).__name__}: {exc}")
            continue'''
assert s.count(old4) == 1, f"error anchor={s.count(old4)}"
s = s.replace(old4, new4, 1)

s = s.replace('''    tot_r = tot_m = 0''', '''    tot_r = tot_m = errors = 0''', 1)
s = s.replace('''    return {"files": len(files), "requests": tot_r, "turns": tot_m,
            "seconds": round(time.time() - t0, 1)}''',
              '''    if errors:
        print(f"  WARNING: {errors} file(s) failed; their rows may be missing")
    return {"files": len(files), "requests": tot_r, "turns": tot_m,
            "errors": errors, "seconds": round(time.time() - t0, 1)}''', 1)

ast.parse(s)
io.open(P, "w", encoding="utf-8", newline="\n").write(s)
print("isolation_level=None set; BEGINs guarded by in_transaction; failures counted")
print("parses OK")

# ── prove it on a small database before touching the real one ──
import glob
ws = os.path.join(os.environ["APPDATA"], "Code", "User", "workspaceStorage")
files = sorted(glob.glob(os.path.join(ws, "*", "chatSessions", "*.jsonl")),
               key=os.path.getsize, reverse=True)[:40]
test = os.path.join(os.path.expanduser("~"), ".fsearch", "txverify.db")
for suf in ("", "-wal", "-shm"):
    if os.path.exists(test + suf):
        os.remove(test + suf)

import importlib.util
spec = importlib.util.spec_from_file_location("ci", P)
ci = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ci)

con = ci.connect(test)
written = 0
failed = 0
for f in files:
    try:
        r = ci.ingest_file(con, f, "vscode")
        written += r["messages"]
    except Exception as exc:
        failed += 1
        print("   FAILED", os.path.basename(f)[:30], type(exc).__name__, str(exc)[:70])
n = con.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
f2 = con.execute("SELECT COUNT(*) FROM msg_fts").fetchone()[0]
con.close()
print(f"\n40 largest files -> messages={n:,} (returned {written:,}), fts={f2:,}, "
      f"failed={failed}")
assert n == f2, "base and FTS disagree"
assert n > 0, "no messages written at all"
print("PASS: the transaction error is gone and rows are written")
