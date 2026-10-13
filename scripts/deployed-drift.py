#!/usr/bin/env python3
"""deployed-drift.py — is the script that RUNS the script in the repo?

THE GAP THIS FILLS, and it was found the hard way twice in one program.

`preset-drift.py` checks the INSTRUCTION surface (the presets and skills a machine loads).
`assert-bin-matches-repo.py` checks one curated manifest of the text-line scripts on the authority.
Neither checks the ordinary scripts the authority actually executes out of `/usr/local/bin`.

MEASURED 2026-10-13, on `/usr/local/bin` of secratary-cloud, seven of 62 files resolving to a repo
file -- five MATCH and two DRIFT. And in those two the **DEPLOYED copy was the newer one**:

    production-comms-freshness.py   repo 8,345 B  vs deployed 16,420 B
    stripe-key-watch.py             repo 9,373 B  vs deployed  9,125 B

Both carried real work that had landed only in the running location: a cloud port with
environment-overridable paths and a read-only authority DB, and a corrected key-backup path that
reports an absent source rather than faking it. In the same hour, `journal/tools/journal.py` had the
opposite drift -- the repo was ahead and the deployed copy was two fixes behind.

**So direction is the actionable part, and this reports it.** A repo that is AHEAD means work to
deploy (`presets`-style). A deployed file that is AHEAD means work to recover -- and that is the
direction nobody looks for, because the running one is fine and nothing is visibly broken.

USAGE
    deployed-drift.py                                  # discover and compare
    deployed-drift.py --host secratary-cloud --deployed-dir /usr/local/bin
    deployed-drift.py --json
    deployed-drift.py --only-scripts                   # skip non-.py/.sh/.mjs files

EXIT
    0  every compared file matches
    1  at least one DRIFT (either direction)
    2  could not do the job (no repo, host unreachable, nothing compared) -- never a pass
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

# Files the estate deliberately keeps different in the two places, with the reason. An exclusion
# without a reason is how a real drift gets hidden, so every row must say why.
EXCLUDE = {
    # Deployed wrappers that set environment and call the repo script; they are supposed to differ.
    "transcript-archive-pass.sh": "a thin wrapper that sets TRANSCRIPT_* and calls the repo runner",
}


def sha_of(p: Path) -> str | None:
    try:
        h = hashlib.sha256()
        with open(p, "rb") as f:
            for c in iter(lambda: f.read(1 << 20), b""):
                h.update(c)
        return h.hexdigest()
    except OSError:
        return None


def remote_inventory(host: str, ddir: str) -> dict[str, dict]:
    """{basename: {sha, mtime}} for regular files in the deployed directory."""
    script = (
        f"for f in {ddir}/*; do "
        "[ -f \"$f\" ] || continue; "
        "printf '%s\\t%s\\t%s\\n' \"$(basename \"$f\")\" "
        "\"$(sha256sum \"$f\" | cut -c1-64)\" \"$(stat -c %Y \"$f\" 2>/dev/null || echo 0)\"; "
        "done"
    )
    out = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=12", host, script],
                         capture_output=True, text=True, encoding="utf-8", errors="replace",
                         timeout=120)
    if out.returncode != 0:
        raise SystemExit(f"deployed-drift: could not list {ddir} on {host} (rc={out.returncode}): "
                         f"{(out.stderr or '')[:300]} -- exit 2, not a pass.")
    inv = {}
    for line in (out.stdout or "").splitlines():
        parts = line.rstrip("\n").split("\t")
        if len(parts) == 3 and parts[0]:
            inv[parts[0]] = {"sha": parts[1], "mtime": int(parts[2] or 0)}
    return inv


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="secratary-cloud")
    ap.add_argument("--deployed-dir", default="/usr/local/bin")
    ap.add_argument("--repo", default=None)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--only-scripts", action="store_true",
                    help="only .py/.sh/.mjs/.mts basenames")
    a = ap.parse_args()

    repo = Path(a.repo).expanduser() if a.repo else None
    if repo is None:
        here = Path(__file__).resolve()
        for cand in (here.parent.parent, here.parent.parent.parent):
            if (cand / "scripts").is_dir():
                repo = cand
                break
    if repo is None or not (repo / "scripts").is_dir():
        print("deployed-drift: cannot find a harness-config checkout with scripts/ -- pass --repo. "
              "Exit 2, not a pass.", file=sys.stderr)
        return 2

    inv = remote_inventory(a.host, a.deployed_dir)
    if not inv:
        print(f"deployed-drift: {a.deployed_dir} on {a.host} listed no regular files -- exit 2, "
              "not a pass.", file=sys.stderr)
        return 2

    rows, drift, only_deployed = [], [], []
    compared = 0
    for name in sorted(inv):
        if a.only_scripts and Path(name).suffix not in (".py", ".sh", ".mjs", ".mts", ".js"):
            continue
        if name in EXCLUDE:
            rows.append({"name": name, "state": "EXCLUDED", "why": EXCLUDE[name]})
            continue
        src = repo / "scripts" / name
        if not src.is_file():
            only_deployed.append(name)
            rows.append({"name": name, "state": "ONLY-DEPLOYED",
                         "deployed_sha": inv[name]["sha"][:12],
                         "deployed_path": f"{a.host}:{a.deployed_dir}/{name}"})
            continue
        compared += 1
        r_sha, d_sha = sha_of(src), inv[name]["sha"]
        if r_sha == d_sha:
            state, direction = "MATCH", None
        else:
            state = "DRIFT"
            r_mtime = int(src.stat().st_mtime)
            # Direction matters more than the fact: repo-ahead means deploy it, deployed-ahead means
            # recover it, and the two need opposite actions.
            direction = "REPO-IS-AHEAD" if r_mtime > inv[name]["mtime"] else "DEPLOYED-IS-AHEAD"
            drift.append(name)
        rows.append({"name": name, "state": state, "direction": direction,
                     "repo_path": str(src), "repo_sha": (r_sha or "")[:12],
                     "repo_bytes": src.stat().st_size,
                     "deployed_path": f"{a.host}:{a.deployed_dir}/{name}",
                     "deployed_sha": d_sha[:12], "deployed_mtime": inv[name]["mtime"]})

    if a.json:
        print(json.dumps({"host": a.host, "deployed_dir": a.deployed_dir, "repo": str(repo),
                          "deployed_files": len(inv), "compared": compared,
                          "drift": drift, "only_deployed": only_deployed, "rows": rows}, indent=2))
        return 1 if drift else 0

    for r in rows:
        if a.quiet and r["state"] in ("MATCH", "ONLY-DEPLOYED"):
            continue
        if r["state"] == "MATCH":
            print(f"MATCH         {r['name']:<40} sha={r['repo_sha']}")
        elif r["state"] == "EXCLUDED":
            print(f"EXCLUDED      {r['name']:<40} {r['why']}")
        elif r["state"] == "ONLY-DEPLOYED":
            print(f"ONLY-DEPLOYED {r['name']:<40} runs on {r['deployed_path']} and is in NO repo path")
        else:
            print(f"DRIFT         {r['name']:<40} {r['direction']:<17} "
                  f"repo={r['repo_bytes']}B/{r['repo_sha']}  deployed={r['deployed_sha']}")
    print()
    print(f"{a.host}:{a.deployed_dir} -- {len(inv)} files, {compared} compared to the repo, "
          f"match={compared - len(drift)}, drift={len(drift)}, only-deployed={len(only_deployed)}")
    if drift:
        print()
        print("  REPO-IS-AHEAD      -> the fix is to DEPLOY it (`sync.py`, or copy the file).")
        print("  DEPLOYED-IS-AHEAD   -> the fix is to RECOVER it: real work landed only in the")
        print("                         running location and the repo is behind. Nobody notices this")
        print("                         direction, because the running copy is fine.")
    return 1 if drift else 0


if __name__ == "__main__":
    sys.exit(main())
