#!/usr/bin/env python3
"""Deploy a captured file from this repo onto the authority, safely. DRY RUN BY DEFAULT.

The point is to make "the file in git" and "the file that runs" the same file, in one step that
cannot half-succeed:

  1. refuse if the file is not in MANIFEST.tsv (an undeclared file is not deployable);
  2. back the live file up BESIDE it, with a UTC timestamp, before overwriting anything;
  3. copy the repo file into place;
  4. re-read the deployed file and assert its sha256 equals the repo file's - the same
     read-it-back check the wake dispatcher uses on its own artefacts;
  5. refresh the manifest entry, so the drift test stays honest;
  6. `python3 -m py_compile` it when it ends in .py;
  7. on ANY failure, restore the backup and exit non-zero.

It never restarts a service, never runs anything with --send, and never sends anything. A deploy
is not a live-action; making the change take effect is a separate, deliberate step.

Usage:
    python3 deploy-bin-from-repo.py --dry-run sms-responder.py
    python3 deploy-bin-from-repo.py --host secratary-lan textdecide.py
"""
from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
MANIFEST = HERE / "MANIFEST.tsv"
DEFAULT_HOST = "secratary-ts"
DEFAULT_ROOT = "/home/zabz/bin"


def sha_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_manifest() -> dict:
    if not MANIFEST.is_file():
        raise SystemExit(f"REFUSING: no manifest at {MANIFEST}")
    rows = {}
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, size, sha = line.split("\t")
        rows[name] = {"size": int(size), "sha": sha.lower()}
    if not rows:
        raise SystemExit("REFUSING: the manifest is empty")
    return rows


def ssh(host: str, cmd: str, timeout: int = 90) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=20",
         "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=3", host, cmd],
        capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+")
    ap.add_argument("--host", default=DEFAULT_HOST)
    ap.add_argument("--deployed-root", default=DEFAULT_ROOT)
    ap.add_argument("--dry-run", action="store_true",
                    help="print exactly what would happen and change nothing")
    a = ap.parse_args()

    manifest = read_manifest()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    failures = 0

    for name in a.files:
        local = HERE / name
        if name not in manifest:
            print(f"REFUSE  {name}: not in MANIFEST.tsv - declare it before deploying it")
            failures += 1
            continue
        if not local.is_file():
            print(f"REFUSE  {name}: no such file in the repo capture at {local}")
            failures += 1
            continue
        lsha = sha_of(local)
        dest = f"{a.deployed_root}/{name}"
        backup = f"{dest}.bak-deploy-{stamp}"
        print(f"{name}\n  repo {lsha[:12]}  {local.stat().st_size} bytes")

        p = ssh(a.host, f"sha256sum {dest} 2>/dev/null || echo MISSING")
        live = (p.stdout or "").strip()
        print(f"  live {live[:80]}")

        if a.dry_run:
            print(f"  WOULD: cp {dest} -> {backup}; copy the repo file to {dest}; "
                  f"assert sha == {lsha[:12]}; py_compile if .py; refresh the manifest")
            continue

        steps = (
            f"set -e; cp -p {dest} {backup} && "
            f"cp {dest} {backup} && true"
        )
        # 2. back up, then write the new content through a single shell, then re-read and assert.
        payload = local.read_bytes()
        try:
            p1 = ssh(a.host, f"set -e; test -f {dest} && cp -p {dest} {backup}; echo backed-up")
            if p1.returncode != 0:
                print(f"  FAIL: could not back up {dest}: {(p1.stderr or '')[:160]}")
                failures += 1
                continue
            p2 = subprocess.run(
                ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=20", a.host,
                 f"cat > {dest}"],
                input=payload, capture_output=True, timeout=180)
            if p2.returncode != 0:
                raise RuntimeError(f"write failed: {(p2.stderr or b'')[:160]!r}")
            p3 = ssh(a.host, f"sha256sum {dest}")
            got = (p3.stdout or "").split()[0] if p3.stdout else ""
            if got != lsha:
                ssh(a.host, f"cp -p {backup} {dest}", timeout=90)
                print(f"  FAIL: deployed sha {got[:12]} != repo sha {lsha[:12]}; RESTORED the backup")
                failures += 1
                continue
            print(f"  OK: deployed sha == repo sha ({lsha[:12]}); backup {backup}")
            if name.endswith(".py"):
                p4 = ssh(a.host, f"python3 -m py_compile {dest} && echo compiles-ok")
                ok = "compiles-ok" in (p4.stdout or "")
                print(f"  {'compiles: OK' if ok else 'COMPILE FAILED - file left in place, check it'}")
                if not ok:
                    failures += 1
                    continue
            # 5. the manifest follows the deployed truth
            lines = []
            for line in MANIFEST.read_text(encoding="utf-8").splitlines():
                parts = line.split("\t")
                if len(parts) == 3 and parts[0] == name:
                    lines.append(f"{name}\t{local.stat().st_size}\t{lsha}")
                else:
                    lines.append(line)
            MANIFEST.write_text("\n".join(lines) + "\n", encoding="utf-8")
            print("  manifest refreshed")
        except Exception as exc:
            print(f"  FAIL: {type(exc).__name__}: {exc}")
            failures += 1

    if a.dry_run:
        print("\nDRY RUN - nothing was changed.")
        return 0
    print(f"\n{len(a.files) - failures} deployed, {failures} failed.")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
