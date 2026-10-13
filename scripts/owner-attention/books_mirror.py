import pathlib, subprocess, sqlite3, json

REMOTE = "secratary-ts"
RDB = "/home/zabz/accounting-data/books.db"
LOCAL = "/root/accounting-data/books.db"

con = sqlite3.connect(LOCAL)
cols = [r[1] for r in con.execute("PRAGMA table_info(obligations)")]
print("local cols:", cols, len(cols))

# JSON is the only format that survives tabs, pipes and quotes in the data.
r = subprocess.run(
    ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", REMOTE,
     f"sqlite3 {RDB} \"select json_group_array(json_object(" +
     ",".join(f"'{c}', \"{c}\"" for c in cols) + ")) from obligations\""],
    capture_output=True, text=True, timeout=180)
print("rc:", r.returncode, "| bytes:", len(r.stdout), "| stderr:", r.stderr.strip()[:150])
if r.returncode != 0 or not r.stdout.strip():
    # fall back to one JSON object per line
    r = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", REMOTE,
         f"sqlite3 {RDB} \"select json_object(" +
         ",".join(f"'{c}', \"{c}\"" for c in cols) + ") from obligations\""],
        capture_output=True, text=True, timeout=180)
    rows = [json.loads(l) for l in r.stdout.split("\n") if l.strip()]
else:
    rows = json.loads(r.stdout)
print("rows parsed:", len(rows))
if rows:
    print("sample:", json.dumps(rows[0])[:300])

q = f"INSERT OR REPLACE INTO obligations ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})"
ins = 0
for row in rows:
    try:
        con.execute(q, [row.get(c) for c in cols])
        ins += 1
    except Exception as e:
        print("  skip:", str(e)[:120])
con.commit()
print("inserted:", ins)
print("verify:", con.execute("SELECT COUNT(*), MIN(due_on), MAX(due_on) FROM obligations").fetchone())
con.close()

