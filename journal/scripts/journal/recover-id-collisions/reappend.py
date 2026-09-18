import json
import os
import re
import subprocess
import sys
import tempfile

COLL = r"C:\Users\ezabz\.dsh-network\journal-collisions.json"
JOURNAL = r"C:\Users\ezabz\code\harness-config\journal\tools\journal.py"

with open(COLL, encoding="utf-8") as fh:
    data = json.load(fh)
if isinstance(data, dict):
    data = [data]

print(f"re-appending {len(data)} collided entries")
ok = 0
for item in data:
    src = item["src"]
    rel = item["rel"]
    with open(src, encoding="utf-8") as fh:
        text = fh.read()
    lines = text.split("\n")

    m = re.match(r"<!-- e:(\w+)\|([A-Z]\d+)\|([^|]*)\|([^|]*)\|([^ ]*) -->", lines[0])
    if not m:
        print(f"  SKIP (unparseable header): {rel}")
        continue
    kind, oid, date, host, status = m.groups()

    heading = lines[1].strip().strip("*").strip()
    rest = heading
    if rest.startswith(oid):
        rest = rest[len(oid):].lstrip(" ·")
    rest = re.sub(r"^\d{4}-\d{2}-\d{2}\s*·\s*", "", rest)
    title = rest.strip().strip("*").strip()

    body_lines = lines[2:]
    while body_lines and body_lines[-1].strip() == "":
        body_lines.pop()
    j2 = ""
    if body_lines and body_lines[-1].startswith("<!-- j2"):
        j2 = body_lines.pop()
    body = "\n".join(body_lines).strip("\n")

    tags = (re.search(r"tags=([^ ]*)", j2) or [None, ""])[1]
    refs = (re.search(r"refs=([^ ]*)", j2) or [None, ""])[1]

    note = (
        "*(Re-appended 2026-09-16 after an id collision. This record was first written under id `%s` on a checkout that was "
        "nine commits behind `origin/master`, so that id already meant a different entry written on another machine. `journal.py` "
        "allocated a fresh id rather than let one id mean two things; the content below is unchanged apart from this note.)*\n\n"
        % oid
    )

    bodyfile = os.path.join(tempfile.gettempdir(), "journal-reappend-body.txt")
    with open(bodyfile, "w", encoding="utf-8") as fh:
        fh.write(note + body)

    cmd = ["python", JOURNAL, "append", kind, "--title", title, "--body-file", bodyfile, "--host", host]
    if tags:
        cmd += ["--tags", tags]
    if refs:
        cmd += ["--refs", refs]

    print("--- %s  (%s, was %s)" % (rel, kind, oid))
    proc = subprocess.run(cmd, capture_output=True, text=True)
    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    print("    " + (out if out else err if err else "(no output)"))
    sys.stdout.flush()
    if proc.returncode == 0:
        ok += 1

print(f"done: {ok}/{len(data)} re-appended")
