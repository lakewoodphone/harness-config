#!/usr/bin/env python3
"""One pass over the user profile looking for customer device data outside the allowed folder.

Matches on filename, which is how these arrive: WhatsApp stores (msgstore*.db.crypt*), Android
backups (*.ab), phone dumps, iTunes backups (Manifest.db + Info.plist in a UDID-named dir), and
carved/extracted trees. Reports path, size, mtime. Excludes Downloads\\customer data (the one
allowed home) and anything already known.
"""
import os, sys, json, time

ROOTS = [r"C:\Users\ezabz"]
SKIP = (r"C:\Users\ezabz\Downloads\customer data", r"C:\Users\ezabz\Backups", r"C:\Users\ezabz\.dsh\tmp")
OUT = r"C:\Users\ezabz\Code\_audit\customer-data-scan.json"

def interesting(name, path):
    n = name.lower()
    if n.startswith("msgstore") and (".crypt" in n or n.endswith(".db")):
        return "whatsapp-store"
    if n.endswith(".crypt14") or n.endswith(".crypt15"):
        return "whatsapp-store"
    if n.endswith(".ab") and "backup" in path.lower():
        return "android-backup"
    if n == "manifest.db" and "mobilesync" in path.lower():
        return "itunes-backup"
    if n in ("backupinfo.ini", "deivce.ini", "device.ini"):
        return "transfer-staging"
    if n.endswith((".tar.gz", ".tgz")) and ("whatsapp" in n or "backup" in n) and os.path.getsize(os.path.join(path, name)) > 200 * 2**20:
        return "backup-archive"
    return None

found = []
files = 0
t0 = time.time()
for root in ROOTS:
    for dp, dn, fn in os.walk(root):
        if any(dp.startswith(s) for s in SKIP):
            dn[:] = []
            continue
        files += 1
        if files % 200000 == 0:
            print("  %d dirs, %d hits, %.0fs" % (files, len(found), time.time() - t0), flush=True)
        for f in fn:
            kind = interesting(f, dp)
            if not kind:
                continue
            p = os.path.join(dp, f)
            try:
                st = os.stat(p)
            except OSError:
                continue
            found.append({"kind": kind, "path": p, "bytes": st.st_size, "mtime": time.strftime("%Y-%m-%d", time.localtime(st.st_mtime))})

with open(OUT, "w", encoding="utf-8") as fh:
    json.dump(found, fh, indent=1)
found.sort(key=lambda r: -r["bytes"])
for r in found[:25]:
    print("%8.2f GiB  %s  %s  %s" % (r["bytes"] / 2**30, r["mtime"], r["kind"], r["path"]))
print("TOTAL %d hits, %.2f GiB, %.0fs" % (len(found), sum(r["bytes"] for r in found) / 2**30, time.time() - t0))
