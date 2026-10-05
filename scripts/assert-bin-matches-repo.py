#!/usr/bin/env python3
"""Assert that the files captured in scripts/deployed/bin/ still match the files
that are actually deployed on the authority.

This is the guard for a measured failure class in this system: the files that RUN
the owner's text line live in /home/zabz/bin/ on the authority, and they are NOT
what is in git. There are (at least) three different sms-responder.py files in
circulation, and an audit that reads the wrong one reports the wrong facts with
full confidence. The same shape of failure is recorded in journal lesson L2798: a
live-looking artifact read as work-happening while the real thing was frozen.

For every entry in the manifest this prints exactly one line:

    MATCH    <name>  deployed=<sha>  captured=<sha>
    DRIFT    <name>  deployed=<sha>  captured=<sha>
    MISSING  <name>  deployed=<sha|ABSENT>  captured=<sha|ABSENT>

Exit status:
    0  every manifest entry is MATCH
    1  at least one entry is DRIFT or MISSING
    2  the tool could not do its job (unreadable/empty manifest, no authority,
       or --only matched nothing) - never reported as a pass

It never writes anything: no file in the repo, no file on the authority, and no
manifest update.  See TRANSPORT below.

TRANSPORT (deliberately disclosed, MEASURED 2026-09-29 on ZABZ-TECH):
`ssh` output captured through a *pipe* is truncated on this host - a command such
as `hostname; whoami; sha256sum FILE` delivers only `secratary` and then stalls
until killed, and a sha256sum loop delivers only its first iteration. The same
command with ssh's stdout redirected to a file handle returns complete output in
about a second. So ssh's stdout is pointed at a short-lived file in the OS temp
directory, which is read and deleted at once. That temp file is a transport
detail, not a write to the repo, the manifest, or the authority; --only and all
comparison logic remain read-only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile

SSH_ALIAS = "secratary-lan"
SSH_TIMEOUT = 90
END_MARKER = "__WSC_END__"

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_MANIFEST = os.path.join(REPO_ROOT, "scripts", "deployed", "bin", "MANIFEST.json")


def die(msg: str, code: int = 2) -> "NoReturn":  # type: ignore[valid-type]
    print("assert-bin-matches-repo: FATAL: " + msg, file=sys.stderr)
    raise SystemExit(code)


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_manifest(path: str) -> list[dict]:
    """Read the manifest. Any problem here is fatal and loud - an unreadable
    manifest must never turn into an empty pass."""
    if not os.path.exists(path):
        die(f"manifest not found: {path}")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = fh.read()
    except OSError as exc:
        die(f"manifest unreadable: {path}: {exc}")
    if not raw.strip():
        die(f"manifest is empty: {path}")
    try:
        doc = json.loads(raw)
    except json.JSONDecodeError as exc:
        die(f"manifest is not valid JSON: {path}: {exc}")
    if not isinstance(doc, dict):
        die(f"manifest root is {type(doc).__name__}, expected object: {path}")
    files = doc.get("files")
    if not isinstance(files, list) or not files:
        die(f"manifest has no non-empty 'files' list: {path}")
    for i, entry in enumerate(files):
        if not isinstance(entry, dict):
            die(f"manifest files[{i}] is {type(entry).__name__}, expected object")
        for key in ("name", "deployed_path", "repo_path"):
            if not entry.get(key):
                die(f"manifest files[{i}] is missing '{key}'")
    return files


def ssh_sha_map(paths: list[str]) -> dict[str, str]:
    """One ssh call: report the sha256 of each deployed path, or mark it ABSENT.

    ssh's stdout goes to a temp file, not a pipe (see TRANSPORT in the module
    docstring). Raises RuntimeError on any transport problem so the caller can
    exit 2 rather than mistake an unreachable authority for a clean result.
    """
    quoted = " ".join("'" + p.replace("'", "'\\''") + "'" for p in paths)
    remote = (
        "for p in " + quoted + "; do "
        'if [ -f "$p" ]; then '
        'printf \'PRESENT %s %s\\n\' "$(sha256sum "$p" | cut -d\' \' -f1)" "$p"; '
        "else "
        'printf \'ABSENT %s\\n\' "$p"; '
        "fi; done; echo " + END_MARKER
    )
    fd, tmp = tempfile.mkstemp(prefix="ws-c-drift-", suffix=".out")
    os.close(fd)
    try:
        with open(tmp, "wb") as out:
            try:
                proc = subprocess.run(
                    ["ssh", "-o", "ConnectTimeout=10", "-o", "BatchMode=yes",
                     SSH_ALIAS, remote],
                    stdout=out, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
                    timeout=SSH_TIMEOUT,
                )
            except FileNotFoundError:
                raise RuntimeError("ssh executable not found on PATH")
            except subprocess.TimeoutExpired:
                raise RuntimeError(f"ssh to {SSH_ALIAS} timed out after {SSH_TIMEOUT}s")
        stderr = (proc.stderr or b"").decode("utf-8", "replace").strip()
        if proc.returncode != 0:
            raise RuntimeError(f"ssh to {SSH_ALIAS} exited {proc.returncode}: {stderr}")
        with open(tmp, "r", encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass

    if END_MARKER not in text:
        raise RuntimeError(
            f"ssh to {SSH_ALIAS} returned incomplete output (no {END_MARKER} marker); "
            f"got {text!r}"
        )

    found: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line == END_MARKER:
            continue
        parts = line.split()
        if len(parts) == 3 and parts[0] == "PRESENT":
            found[parts[2]] = parts[1]
        elif len(parts) == 2 and parts[0] == "ABSENT":
            found[parts[1]] = ""
        else:
            raise RuntimeError(f"unparseable authority output line: {line!r}")
    return found


def matches_only(entry: dict, wanted: list[str]) -> bool:
    hay = {entry["name"], entry["deployed_path"], entry["repo_path"]}
    for want in wanted:
        if want in hay:
            return True
        base = os.path.basename(entry["deployed_path"])
        if want == base:
            return True
        if entry["repo_path"].replace("\\", "/").endswith(want.replace("\\", "/")):
            return True
    return False


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Compare the captured repo copies against the authority's live files.")
    ap.add_argument("--manifest", default=DEFAULT_MANIFEST,
                    help=f"manifest to read (default: {DEFAULT_MANIFEST})")
    ap.add_argument("--only", action="append", default=[], metavar="PATH",
                    help="check only this file (repo-relative path, deployed path, "
                         "or basename); repeatable")
    args = ap.parse_args(argv)

    entries = load_manifest(args.manifest)

    if args.only:
        selected = [e for e in entries if matches_only(e, args.only)]
        if not selected:
            die("--only matched no manifest entry: " + ", ".join(args.only))
        entries = selected

    print(f"manifest : {args.manifest}")
    print(f"authority: {SSH_ALIAS}")
    print(f"checking : {len(entries)} file(s)")
    print()

    try:
        live = ssh_sha_map([e["deployed_path"] for e in entries])
    except RuntimeError as exc:
        die(str(exc))

    counts = {"MATCH": 0, "DRIFT": 0, "MISSING": 0}
    rows = []
    for entry in entries:
        name = entry["name"]
        deployed_path = entry["deployed_path"]
        captured_path = os.path.join(REPO_ROOT, entry["repo_path"])

        deployed_sha = live.get(deployed_path)
        if deployed_sha is None:
            # The authority did not report this path at all: it was requested and
            # skipped, which is itself a transport defect, not a clean result.
            die(f"authority returned no result for {deployed_path}")

        captured_sha = ""
        if not os.path.exists(captured_path):
            captured_sha = ""
        else:
            try:
                captured_sha = sha256_file(captured_path)
            except OSError as exc:
                die(f"cannot read captured file {captured_path}: {exc}")

        if not deployed_sha:
            status = "MISSING"
        elif not captured_sha:
            status = "MISSING"
        elif deployed_sha == captured_sha:
            status = "MATCH"
        else:
            status = "DRIFT"
        counts[status] += 1
        rows.append((status, name,
                     deployed_sha or "ABSENT",
                     captured_sha or "ABSENT"))

    width = max(len(r[1]) for r in rows)
    for status, name, dep, cap in rows:
        print(f"{status:<7} {name:<{width}}  deployed={dep}  captured={cap}")

    print()
    print(f"summary: {counts['MATCH']} MATCH, {counts['DRIFT']} DRIFT, "
          f"{counts['MISSING']} MISSING")
    if counts["DRIFT"] or counts["MISSING"]:
        print("RESULT: FAIL - the repo copies no longer describe the deployed files.")
        return 1
    print("RESULT: PASS - every captured file is byte-identical to the deployed file.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
