import glob
import json
import os
import re
import sys

files = sorted(glob.glob("/root/.dsh/logs/startup-*.log"), key=os.path.getmtime)
if not files:
    print("no startup logs")
    sys.exit(0)
path = files[-1]
print("file:", path)
text = open(path, encoding="utf-8", errors="replace").read()

# The diagnostic is a JS-ish dump; pull every entry block that mentions a web module or a web-ish id.
for m in re.finditer(r"id: '([^']+)',\s*\n\s*module: '([^']+)',\s*\n\s*required: (\w+),\s*\n\s*fiberState: (\d+),\s*\n\s*outcome: ", text):
    ident, module, req, state = m.groups()
    if "web" not in module.lower() and "web" not in ident.lower():
        continue
    tail = text[m.end():m.end() + 400]
    tail = " ".join(tail.split())
    print(f"  {ident:22} {module:52} required={req} fiberState={state}")
    print(f"    {tail[:260]}")

# and any explicit module-load errors
for m in re.finditer(r"(Cannot find module[^\n']{0,160}|ERR_MODULE_NOT_FOUND[^\n']{0,120})", text):
    print("  LOAD ERROR:", m.group(1)[:200])
