#!/usr/bin/env python3
"""cron-script-guard.py - make the "a branch switch un-deployed a cron script" failure
self-healing and LOUD.

WHY THIS EXISTS
Measured 2026-10-07: 25 of the ~60 cron entries on secratary run a script from inside a
git working tree (personal-secretary-mvp, ceo-kernel, harness-config). A `git checkout`
of a different branch removes any file that branch does not contain, and the entry then
fails with "not found" forever, silently. That is exactly how the company's offsite
backup leg died for eight hours on 2026-10-06:

    sh: 1: /home/zabz/personal-secretary-mvp/scripts/server/company-offsite-push.sh: not found

This guard runs every few minutes, decodes the real crontab, finds every script a cron
entry depends on that lives inside a known repo, and:
  * restores it from git if it is MISSING but tracked at that path (self-heal);
  * reports it loudly if it is missing AND not tracked (alert, never silent);
  * reports where a missing script was restored from, so the heal is visible.
It changes nothing about the crontab and restarts nothing.

READ-ONLY TOWARD EVERYTHING EXCEPT the missing script files it restores.

── PORTED TO secratary-cloud, 2026-10-11 ────────────────────────────────────────────────────────
Three changes, each because the office version's assumption is false on the new authority:

1. HOME is no longer assumed. On the cloud box everything runs as root from `/opt/company`,
   `/usr/local/bin` and `/root`; there is no `/home/zabz`. The base is now
   `$CRON_SCRIPTS_HOME` (default `$HOME`), and the repos it will examine are DISCOVERED by
   finding `.git` directories under that base rather than listed by hand -- a hand-written list
   is how the office version silently stopped covering a repo when one moved.
2. The payload check is now an ASSERTION, not a fallback. The office version treated "payload
   did not decode" as "not wrapped" and then scanned the undecoded text -- so a decoding bug
   would have looked exactly like a healthy run. A payload that does not decode is now reported
   as a finding in its own right (`undecoded_payloads`), and `payloads_decoded` is written to the
   status file on every run so "this guard is checking real programs" is measurable, not assumed.
   (This is the pair of the same defect fixed in cron-target-guard.py: ~60 crontab entries are
   `cron-wrap.sh` wrappers, and a guard that never decodes them checks one program 60 times.)
3. `--crontab FILE` so the guard can be run against a captured crontab -- that is how it is
   proved to fire instead of being taken on trust.
"""
from __future__ import annotations

import argparse
import base64
import binascii
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone

HOME = os.path.expanduser(os.environ.get("CRON_SCRIPTS_HOME") or "~")
STATUS = os.environ.get("CRON_SCRIPTS_STATUS") or os.path.join(HOME, ".cron-scripts", "status.json")
LOG = os.path.join(os.path.dirname(STATUS), "guard.log")

WRAP = "cron-wrap.sh"
# a shell-ish token that looks like an absolute script path. Deliberately NOT anchored to $HOME:
# on the cloud authority the interesting scripts live in /opt/company and /usr/local/bin, and a
# guard that only looks under one home directory is the same blindness it exists to fix.
PATH_RE = re.compile(r"/(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+\.(?:sh|py|mjs|js)")
B64_RE = re.compile(r"^[A-Za-z0-9+/]{16,}={0,2}$")
DECODE_DEPTH = 4


def discover_repos(base: str, max_depth: int = 3) -> list[str]:
    """Every git working tree under `base`, newest-path-first. No hand-written repo list."""
    found: list[str] = []
    base = base.rstrip(os.sep) or os.sep
    for root, dirs, _files in os.walk(base, topdown=True):
        rel = os.path.relpath(root, base)
        depth = 0 if rel == "." else rel.count(os.sep) + 1
        if depth >= max_depth:
            dirs[:] = []
        # never walk into the trees that make this expensive
        dirs[:] = [d for d in dirs if d not in (".git", "node_modules", "__pycache__", ".venv",
                                                "venv", "site-packages", ".cache")]
        if os.path.isdir(os.path.join(root, ".git")):
            found.append(root)
    return sorted(found)


REPOS = []
for _base in (os.environ.get("CRON_SCRIPTS_REPO_ROOTS") or
              ":".join([HOME, os.path.join(HOME, "code"), "/opt", "/srv", "/usr/local/share"])):
    if _base and os.path.isdir(_base):
        for _r in discover_repos(_base):
            if _r not in REPOS:
                REPOS.append(_r)
REPOS.sort()
# Paths that are legitimately outside a repo, or intentionally not tracked.
SKIP_PREFIXES = tuple(os.path.join(HOME, p) for p in (
    "bin", "node", ".fsearch", "scripts", ".cron-scripts", ".cron-targets", ".pain-check",
    ".db-integrity", ".guard-registry", "tmp-rescue", ".store-write-check"))


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def log(msg: str) -> None:
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    line = f"{now()} {msg}"
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")
    print(line)


def crontab_lines(path: str | None = None) -> list[str]:
    """The jobs in the crontab (or in `--crontab FILE`), comments and blanks removed."""
    if path:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except Exception as exc:  # noqa: BLE001
            log(f"ERROR could not read {path}: {exc}")
            return []
        return [l for l in text.splitlines() if l.strip() and not l.strip().startswith("#")]
    try:
        out = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=30)
    except Exception as exc:  # noqa: BLE001
        log(f"ERROR could not read crontab: {exc}")
        return []
    return [l for l in (out.stdout or "").splitlines() if l.strip() and not l.strip().startswith("#")]


def _b64(token: str) -> str | None:
    tok = token.strip().strip("'\"")
    if len(tok) < 8 or not B64_RE.match(tok):
        return None
    try:
        raw = base64.b64decode(tok + "=" * (-len(tok) % 4), validate=True)
    except (binascii.Error, ValueError):
        return None
    try:
        out = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if not out.strip() or "\x00" in out:
        return None
    return out


def decode_wrapped(line: str) -> tuple[str, bool, bool, str]:
    """cron-wrap.sh <name> <base64-of-command> -> (command, was_wrapped, decoded_ok, name).

    Recursive, because a payload may itself be `base64 -d <<< '...'`. Returns `was_wrapped` so a
    payload that could NOT be decoded is reported as a finding rather than silently scanned raw.
    """
    text = line
    name = "?"
    wrapped = False
    decoded_any = False
    for _ in range(DECODE_DEPTH):
        toks = text.split()
        if not toks:
            break
        if os.path.basename(toks[0]) == WRAP:
            wrapped = True
            if len(toks) >= 2:
                name = toks[-2] if len(toks) >= 3 else toks[1]
            if len(toks) >= 3:
                got = _b64(toks[-1])
                if got is not None:
                    decoded_any = True
                    text = got
                    continue
            break
        if any(os.path.basename(t) == "base64" for t in toks):
            got = None
            for t in toks:
                if t.startswith("-"):
                    continue
                got = _b64(t)
                if got is not None:
                    break
            if got is not None:
                decoded_any = True
                text = got
                continue
        break
    return text, wrapped, (decoded_any or not wrapped), name


def repo_of(path: str) -> str | None:
    best = None
    for r in REPOS:
        if path.startswith(r + os.sep) and (best is None or len(r) > len(best)):
            best = r
    return best


def relpath(path: str, repo: str) -> str:
    return os.path.relpath(path, repo)


def tracked_at(repo: str, rel: str) -> bool:
    try:
        r = subprocess.run(["git", "-C", repo, "cat-file", "-e", f"HEAD:{rel}"],
                           capture_output=True, timeout=20)
        return r.returncode == 0
    except Exception:  # noqa: BLE001
        return False


def restore(repo: str, rel: str, dest: str) -> tuple[bool, str]:
    """Write the HEAD version of rel to dest. Never touches the git index."""
    try:
        blob = subprocess.run(["git", "-C", repo, "show", f"HEAD:{rel}"],
                              capture_output=True, timeout=60)
        if blob.returncode != 0:
            return False, (blob.stderr or b"").decode()[:200]
        data = blob.stdout
        if not data:
            return False, "empty blob"
        tmp = dest + ".cronguard.tmp"
        with open(tmp, "wb") as fh:
            fh.write(data)
        os.chmod(tmp, 0o755)
        os.replace(tmp, dest)
        return True, f"{len(data)} bytes from HEAD:{rel}"
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)[:200]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--crontab", default=None, help="read this file instead of `crontab -l`")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    os.makedirs(os.path.dirname(STATUS), exist_ok=True)
    wanted: dict[str, set[str]] = {}   # path -> set of cron job names
    wrapped_lines = 0
    decoded_lines = 0
    undecoded: list[str] = []
    for line in crontab_lines(args.crontab):
        decoded, wrapped, ok, name = decode_wrapped(line)
        if wrapped:
            wrapped_lines += 1
            if ok:
                decoded_lines += 1
            else:
                undecoded.append(line[:200])
        for m in PATH_RE.finditer(decoded):
            p = m.group(0)
            if p.startswith(SKIP_PREFIXES):
                continue
            if repo_of(p):
                wanted.setdefault(p, set()).add(name)

    missing, healed, untracked, ok_count = [], [], [], 0
    for path, jobs in sorted(wanted.items()):
        repo = repo_of(path)
        assert repo
        rel = relpath(path, repo)
        if os.path.exists(path):
            ok_count += 1
            continue
        jl = ",".join(sorted(jobs))
        if tracked_at(repo, rel):
            good, detail = restore(repo, rel, path)
            if good:
                healed.append({"path": path, "jobs": jl, "detail": detail})
                log(f"HEALED {path} (used by cron: {jl}) - restored {detail}")
            else:
                missing.append({"path": path, "jobs": jl, "detail": detail})
                log(f"ALERT cannot restore {path} (used by cron: {jl}): {detail}")
        else:
            untracked.append({"path": path, "jobs": jl})
            log(f"ALERT missing and NOT tracked at HEAD: {path} (used by cron: {jl}) - "
                f"a branch switch cannot be healed for this one; fix the cron path")

    state = {
        "at": now(),
        "host": os.uname().nodename,
        "home": HOME,
        "repos_discovered": REPOS,
        "cron_scripts_watched": len(wanted),
        "present": ok_count,
        "wrapped_cron_lines": wrapped_lines,
        "payloads_decoded": decoded_lines,
        "undecoded_payloads": undecoded,
        "healed_this_run": healed,
        "missing_and_untracked": untracked,
        "missing_unrestorable": missing,
        "ok": not (untracked or missing or undecoded),
    }
    with open(STATUS, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=1)
    summary = {k: v for k, v in state.items() if k not in
               ("healed_this_run", "missing_and_untracked", "missing_unrestorable",
                "repos_discovered", "undecoded_payloads")}
    print(json.dumps(summary, indent=1) if args.json else
          "cron-script-guard: watched=%d present=%d wrapped_lines=%d decoded=%d ok=%s"
          % (len(wanted), ok_count, wrapped_lines, decoded_lines, state["ok"]))
    if healed:
        print(f"healed {len(healed)}: " + ", ".join(h['path'] for h in healed))
    if undecoded:
        print(f"ATTENTION: {len(undecoded)} cron-wrap payload(s) did NOT decode - "
              f"this guard cannot see what they run")
    if untracked or missing:
        print(f"ATTENTION: {len(untracked) + len(missing)} cron script(s) need a real fix")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        log(f"FATAL {exc}")
        sys.exit(1)
