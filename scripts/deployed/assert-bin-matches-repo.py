#!/usr/bin/env python3
"""Does the file that RUNS match the file in GIT?

WHY THIS EXISTS, measured 2026-09-29. `sms-responder.py` on the authority was 70228 bytes /
sha `dda178099128` where it ran, 38917 / `b71e1f3a8a8f` in the authority's copy of this repo, and
56311 on ZABZ-YOGA's copy - three copies, three different files, and NONE of the tracked copies
contained the owner fast path that was live. An audit read the wrong one and reported the wrong
byte count; another worker was told the wrong size in its brief. The same shape of failure had
already frozen `phone-and-tech-full` on an August tree for weeks behind a stale `.git/index.lock`
(lesson L2798), and it is why the owner's own rule is one source of truth per thing.

So: the deployed artefact is CAPTURED into this repo, with a sha for every file, and this script
compares the live file against the captured one. It runs one ssh call for all files - many small
ssh calls to the authority hang after printing, which cost three fleet workers their whole budget
on 2026-09-29.

READ ONLY. It never writes, never deploys, never restarts anything and never sends anything.

Usage:
    python3 assert-bin-matches-repo.py                 # compare everything, human output
    python3 assert-bin-matches-repo.py --json
    python3 assert-bin-matches-repo.py --only sms-responder.py
    python3 assert-bin-matches-repo.py --host secratary-lan

Exit codes: 0 = every compared file MATCHes. 1 = at least one DRIFT or MISSING.
            2 = the manifest could not be read (never mistaken for a pass).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
MANIFEST = HERE / "MANIFEST.tsv"
DEFAULT_HOST = "secratary-ts"
DEFAULT_ROOT = "/home/zabz/bin"


def read_manifest(path: Path) -> list[dict]:
    if not path.is_file():
        raise SystemExit(f"REFUSING: no manifest at {path}. An empty result is not a pass.")
    rows = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) != 3:
            raise SystemExit(f"REFUSING: {path} line {n} is malformed: {line!r}")
        name, size, sha = parts
        rows.append({"name": name, "size": int(size), "sha": sha.lower()})
    if not rows:
        raise SystemExit(f"REFUSING: {path} holds no entries. An empty manifest proves nothing.")
    return rows


def local_sha(p: Path) -> str | None:
    if not p.is_file():
        return None
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def remote_shas(host: str, root: str, names: list[str], timeout: int) -> dict[str, str]:
    """ONE ssh call for every file. Returns {} when the call fails, and the caller must say so."""
    quoted = " ".join("'" + n + "'" for n in names)
    cmd = (f"cd {root} && sha256sum {quoted} 2>/dev/null")
    try:
        p = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=20",
             "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=3", host, cmd],
            capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        return {}
    except Exception:
        return {}
    out = {}
    for line in (p.stdout or "").splitlines():
        parts = line.split()
        if len(parts) == 2 and len(parts[0]) == 64:
            out[parts[1].lstrip("./")] = parts[0].lower()
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default=DEFAULT_HOST)
    ap.add_argument("--deployed-root", default=DEFAULT_ROOT)
    ap.add_argument("--only", default=None, help="compare just this manifest name")
    ap.add_argument("--timeout", type=int, default=90)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    rows = read_manifest(MANIFEST)
    if a.only:
        want = a.only.strip()
        rows = [r for r in rows if r["name"] == want or r["name"].endswith("/" + want)]
        if not rows:
            print(f"REFUSING: {a.only} is not in the manifest. Nothing compared is not a pass.")
            return 2

    names = [r["name"] for r in rows]
    live = remote_shas(a.host, a.deployed_root, names, a.timeout)
    if not live:
        print(f"UNVERIFIED: could not read any sha from {a.host}:{a.deployed_root}.")
        print("  This is NOT a pass and NOT a drift - it is a refusal. Retry, or check the host")
        print("  alias: from the office LAN use secratary-lan; the tailnet alias sometimes hangs.")
        return 2

    verdicts, drifted = [], 0
    for r in rows:
        lsha = local_sha(HERE / r["name"])
        dsha = live.get(r["name"])
        if dsha is None:
            v = "MISSING"
        elif lsha is None:
            v = "MISSING"
        elif dsha == lsha == r["sha"]:
            v = "MATCH"
        else:
            v = "DRIFT"
        if v != "MATCH":
            drifted += 1
        verdicts.append({**r, "local_sha": lsha, "deployed_sha": dsha, "verdict": v})

    if a.json:
        print(json.dumps({"host": a.host, "root": a.deployed_root,
                          "compared": len(rows), "not_matching": drifted,
                          "files": verdicts}, indent=2))
    else:
        print(f"deployed files vs repo capture  ({a.host}:{a.deployed_root})")
        print(f"{'verdict':8} {'file':38} {'repo':12} {'deployed':12}")
        for v in verdicts:
            print(f"{v['verdict']:8} {v['name']:38} "
                  f"{(v['local_sha'] or '-')[:12]:12} {(v['deployed_sha'] or '-')[:12]:12}")
        print()
        print(f"{len(rows) - drifted} of {len(rows)} match; {drifted} do not.")
        if drifted:
            print("DRIFT means the running file is not the file in git. Deploy from the repo with")
            print("deploy-bin-from-repo.py, or re-capture with the manifest, before trusting an audit.")

    return 0 if drifted == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
