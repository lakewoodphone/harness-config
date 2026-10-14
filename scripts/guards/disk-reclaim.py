#!/usr/bin/env python3
"""FLAG FIX: reclaim disk from RE-DOWNLOADABLE caches, and nothing else.

WHY THIS EXISTS (measured on `secratary-cloud`, ledger item prod-db-sync #125)
----------------------------------------------------------------------------
On 2026-10-14 the authority's `/` reached 0 MB free. `/var/log/disk-guard.log`
has the series: CRITICAL at 96-97% from 2026-10-13T20:15Z straight through
2026-10-14T00:45:02Z ("/ at 97.1% (0.0 GB free, 0 MB)"), then 90.5% at 01:00Z
and 45.3% at 01:15Z only after a HUMAN purged by hand. The monitor fired every
15 minutes for hours and nothing acted, because NOTHING RECLAIMS.

The estate was surveyed before this was written (the `estate-systems` rule), and
every existing mechanism was read:

  * `disk-guard.py` (`scripts/guards/`, deployed `/usr/local/bin/`) MONITORS:
    `--json`, `--write-status`, `--selftest`. It has no reclaim path at all.
  * `mesh-hygiene.sh --reclaim` reclaims RESIDENT MEMORY (target + orphan
    processes). It does not free a single byte of disk.
  * `prune-backups.sh` applies the F7 retention policy to BACKUPS only, and the
    backup root `/var/lib/authority-backup` held 0 dirs / 1 MB during the whole
    incident, so it had nothing to give.

So the gap is real and this file fills exactly it. It does not replace any of
the three: `disk-guard.py` still decides WHEN, `prune-backups.sh` still owns
backups, and this decides WHAT of the re-downloadable set to let go.

WHAT IT MAY TOUCH -- and what it may never touch
-----------------------------------------------
The allowlist is CLOSED. A path is only ever a candidate if it is (a) discovered
under `SCAN_ROOTS`, (b) matched by one of the four declared classes below, and
(c) NOT matched by `PROTECTED_PATTERNS`. A candidate that resolves anywhere
inside a protected path aborts the whole run with exit 2 before anything is
removed -- the purge is refused, not partially applied.

`PROTECTED_PATTERNS` carries `/root/authority.db*`, `/tmp/rr-fix`,
`/root/git-rescue-*` and `/opt/company*` because those are the four the ledger
item pins byte-identical, plus the machinery that would otherwise eat itself
(`/root/bin`, `/root/work/work.db*`, `/etc`, `/usr`, `/boot`, `/root/.ssh`,
`/home/zabz/checkout-health-preserved`).

THE GATES -- "purge-gated" is the whole point
---------------------------------------------
`--apply` acts only when ALL of these hold; otherwise it refuses and exits 2:
  1. `--yes` was typed                      (a human/agent said so explicitly);
  2. `/` is at or above `--gate-free-pct`   (default 90% -- a healthy disk is
     NOT purged, so this can never quietly churn caches on a happy machine);
  3. reclaimable >= `--min-bytes`           (default 1 GiB -- never churn for
     crumbs);
  4. no candidate overlaps a protected path.
The default is `--dry-run`, which opens nothing for write and removes nothing.

THE ONE JUDGEMENT CALL, STATED PLAINLY
--------------------------------------
The largest reclaimable pool on this box is `node_modules` in a DEV checkout
(`/root/repos`, 1.51 GiB at 2026-10-14T01:20Z). It is re-downloadable by
construction -- it is `.gitignore`d and `pnpm install` restores it -- but the
project that owns it is active, so reclaiming it costs a reinstall. That is
exactly why class D is gated behind `--yes` AND a >90% disk: it is the last
resort under pressure, not housekeeping. Everything in classes A-C
(download caches, python bytecode, build/test caches) is free of that cost.

Exit codes: 0 reported (dry run) or acted; 2 refused by a gate; 3 error.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import shutil
import stat
import subprocess
import sys
import time

VERSION = "1.0.0"

MIN_AGE_SECONDS_DEFAULT = 900
GATE_FREE_PCT_DEFAULT = 90.0
MIN_BYTES_DEFAULT = 1024 ** 3  # 1 GiB

# ---------------------------------------------------------------------------
# The allowlist. Closed by construction: nothing outside these is ever touched.
# ---------------------------------------------------------------------------

# Class A -- caches whose owning tool re-downloads them on next use.
#  path, the tool that refills it
DOWNLOAD_CACHES = [
    ("/root/.cache/pip", "pip"),
    ("/root/.cache/uv", "uv"),
    ("/root/.local/share/uv", "uv"),
    ("/root/.npm/_cacache", "npm"),
    ("/root/.cache/pnpm", "pnpm"),
    ("/root/.cache/yarn", "yarn"),
    ("/root/.cache/bun", "bun"),
    ("/root/.cache/ms-playwright", "playwright install"),
    ("/root/.cache/puppeteer", "puppeteer"),
    ("/root/.cache/selenium", "selenium-manager"),
    ("/root/.cache/huggingface", "huggingface_hub"),
    ("/root/.cache/torch", "torch.hub"),
    ("/root/.cache/chroma", "chromadb (onnx embedding model)"),
    ("/var/cache/apt/archives", "apt"),
]

# Class B/C -- discovery roots. Walked for `__pycache__`/`*.pyc` and for the
# named build/test cache dirs. `/opt` is walked but `/opt/company` is protected,
# so the live production tree is never a candidate.
SCAN_ROOTS = ["/root", "/home", "/opt", "/srv", "/usr/local"]
BUILD_CACHE_DIRS = [".pytest_cache", ".mypy_cache", ".ruff_cache", ".turbo", ".parcel-cache"]

# Class D -- dependency trees of DEV checkouts, re-installable from the registry.
DEV_JS_ROOTS = ["/root/repos"]

# The four the ledger item pins byte-identical, plus the machinery.
PROTECTED_PATTERNS = [
    "/root/authority.db*",
    "/tmp/rr-fix",
    "/tmp/rr-fix/*",
    "/root/git-rescue-*",
    "/opt/company",
    "/opt/company/*",
    # machinery that must not eat itself
    "/root/bin",
    "/root/bin/*",
    "/root/work/work.db*",
    "/root/hc-main.bundle",
    "/root/.ssh",
    "/home/zabz/checkout-health-preserved",
    "/home/zabz/checkout-health-preserved/*",
    "/etc",
    "/etc/*",
    "/usr",
    "/usr/*",
    "/boot",
    "/boot/*",
    "/var/lib",
    "/var/lib/*",
    "/proc",
    "/sys",
    "/dev",
]

# Paths we fingerprint and re-assert after any run.
FINGERPRINT_PATHS = [
    "/root/authority.db",
    "/root/authority.db-wal",
    "/root/authority.db-shm",
    "/tmp/rr-fix",
    "/root/git-rescue-20261012",
    "/opt/company",
]


# Paths written continuously by another process. Their CONTENT cannot be
# compared across a run and is not evidence of anything: /root/authority.db and
# its -wal/-shm are written by company-api every second. For these, integrity is
# existence + inode (deleted or replaced?) and never a hash or a timestamp.
LIVE_PATTERNS = ["/root/authority.db*"]


def is_live(path: str) -> bool:
    return any(fnmatch.fnmatch(path, pat) for pat in LIVE_PATTERNS)


def is_protected(path: str) -> str | None:
    """Return the protected pattern that covers `path`, or None.

    Both the literal path and its realpath are tested: `/home/zabz/
    personal-secretary-mvp` is a symlink to `/opt/company`, and a purge that
    only tested the symlink spelling would happily delete the production tree.
    """
    for spelling in (path, os.path.realpath(path)):
        for pat in PROTECTED_PATTERNS:
            if fnmatch.fnmatch(spelling, pat):
                return pat
            base = pat.rstrip("*").rstrip(os.sep)
            if spelling == base or spelling.startswith(base + os.sep):
                return pat
    return None


def _du_bytes(path: str) -> int:
    """Allocated bytes under `path` (sum of st_blocks), like `du -B1 -s`."""
    total = 0
    try:
        st = os.lstat(path)
    except OSError:
        return 0
    if stat.S_ISLNK(st.st_mode):
        return 0
    if stat.S_ISREG(st.st_mode):
        return st.st_blocks * 512
    if stat.S_ISDIR(st.st_mode):
        for dirpath, dirnames, filenames in os.walk(path, onerror=lambda e: None,
                                                    followlinks=False):
            for name in filenames:
                try:
                    total += os.lstat(os.path.join(dirpath, name)).st_blocks * 512
                except OSError:
                    pass
            for name in list(dirnames):
                p = os.path.join(dirpath, name)
                if os.path.islink(p):
                    dirnames.remove(name)
    return total


class Candidate:
    __slots__ = ("path", "kind", "bytes", "count", "overlap", "age_s")

    def __init__(self, path, kind, nbytes, count=1, overlap=None, age_s=None):
        self.path = path
        self.kind = kind
        self.bytes = nbytes
        self.count = count
        self.overlap = overlap
        self.age_s = age_s

    def as_dict(self):
        return {"path": self.path, "kind": self.kind, "bytes": self.bytes,
                "entries": self.count, "age_seconds": self.age_s}


def _too_young(path: str, min_age_seconds: int) -> bool:
    try:
        return (time.time() - os.lstat(path).st_mtime) < min_age_seconds
    except OSError:
        return True


def collect_download_caches(min_age_seconds: int) -> list[Candidate]:
    out = []
    for path, tool in DOWNLOAD_CACHES:
        if not os.path.exists(path):
            continue
        overlap = is_protected(path)
        if overlap:
            out.append(Candidate(path, "download-cache:%s" % tool, 0, 0, overlap))
            continue
        if _too_young(path, min_age_seconds):
            continue
        out.append(Candidate(path, "download-cache:%s" % tool, _du_bytes(path)))
    return out


def _walk_roots(roots):
    """Yield (dirpath, dirnames, filenames), pruning protected trees and .git."""
    for root in roots:
        if not os.path.isdir(root) or is_protected(root):
            continue
        for dirpath, dirnames, filenames in os.walk(root, topdown=True,
                                                    followlinks=False,
                                                    onerror=lambda e: None):
            keep = []
            for name in dirnames:
                p = os.path.join(dirpath, name)
                if os.path.islink(p) or is_protected(p) or name == ".git":
                    continue
                keep.append(name)
            dirnames[:] = keep
            yield dirpath, dirnames, filenames


def collect_bytecode_and_build(min_age_seconds: int) -> list[Candidate]:
    out = []
    seen = set()
    roots = [r for r in SCAN_ROOTS if os.path.isdir(r) and not is_protected(r)]
    for dirpath, dirnames, filenames in _walk_roots(roots):
        name = os.path.basename(dirpath)
        if name == "__pycache__" and dirpath not in seen:
            seen.add(dirpath)
            if is_protected(dirpath) or _too_young(dirpath, min_age_seconds):
                continue
            try:
                n = len(os.listdir(dirpath))
            except OSError:
                n = 0
            out.append(Candidate(dirpath, "python-bytecode", _du_bytes(dirpath), n))
            continue
        if name in BUILD_CACHE_DIRS and dirpath not in seen:
            seen.add(dirpath)
            if is_protected(dirpath) or _too_young(dirpath, min_age_seconds):
                continue
            out.append(Candidate(dirpath, "build-cache:%s" % name, _du_bytes(dirpath)))
    return out


def collect_dev_node_modules(min_age_seconds: int) -> list[Candidate]:
    out = []
    for root in DEV_JS_ROOTS:
        if not os.path.isdir(root) or is_protected(root):
            continue
        for dirpath, dirnames, _ in os.walk(root, topdown=True, followlinks=False,
                                            onerror=lambda e: None):
            keep = []
            for name in dirnames:
                p = os.path.join(dirpath, name)
                if os.path.islink(p) or name == ".git":
                    continue
                if name == "node_modules":
                    if is_protected(p):
                        out.append(Candidate(p, "dev-node_modules", 0, 0, is_protected(p)))
                    elif not _too_young(p, min_age_seconds):
                        out.append(Candidate(p, "dev-node_modules", _du_bytes(p)))
                    continue  # never descend into it
                keep.append(name)
            dirnames[:] = keep
    return out


def collect(min_age_seconds: int) -> list[Candidate]:
    return (collect_download_caches(min_age_seconds)
            + collect_bytecode_and_build(min_age_seconds)
            + collect_dev_node_modules(min_age_seconds))


# ---------------------------------------------------------------------------
# Protected-path fingerprint: the "byte-identical" assertion.
# ---------------------------------------------------------------------------

def fingerprint() -> dict:
    import hashlib

    out = {"version": VERSION, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "paths": []}
    for p in FINGERPRINT_PATHS:
        entry = {"path": p, "protected_by": is_protected(p), "exists": os.path.exists(p),
                 "live": is_live(p)}
        if entry["exists"]:
            try:
                st = os.stat(p)
                entry.update({"size": st.st_size, "inode": st.st_ino,
                              "mtime_ns": st.st_mtime_ns})
                if (stat.S_ISREG(st.st_mode) and st.st_size <= 512 * 1024 * 1024
                        and not entry["live"]):
                    h = hashlib.sha256()
                    with open(p, "rb") as fh:
                        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                            h.update(chunk)
                    entry["sha256"] = h.hexdigest()
                    entry["sha256_bytes"] = st.st_size
            except OSError as exc:
                entry["stat_error"] = str(exc)
        out["paths"].append(entry)
    # /opt/company gets the strongest cheap proof it can: git sees no change.
    # --no-optional-locks matters: a plain `git status` opportunistically
    # rewrites .git/index, which would make this tool itself the thing that
    # changed /opt/company.
    if os.path.isdir("/opt/company/.git"):
        try:
            head = subprocess.run(["git", "--no-optional-locks", "-C", "/opt/company",
                                   "rev-parse", "HEAD"],
                                  capture_output=True, text=True, timeout=60).stdout.strip()
            st = subprocess.run(["git", "--no-optional-locks", "-C", "/opt/company",
                                 "status", "--porcelain"],
                                capture_output=True, text=True, timeout=120).stdout
            out["opt_company_git"] = {"head": head,
                                      "status_sha256": hashlib.sha256(st.encode()).hexdigest(),
                                      "status_lines": len(st.splitlines())}
        except Exception as exc:  # noqa: BLE001
            out["opt_company_git"] = {"error": str(exc)}
    return out


# ---------------------------------------------------------------------------

def free_pct_root() -> tuple[float, int, int]:
    st = os.statvfs("/")
    total = st.f_blocks * st.f_frsize
    free = st.f_bavail * st.f_frsize
    used_pct = 100.0 * (total - free) / total if total else 0.0
    return used_pct, free, total


def human(n: int) -> str:
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(n) < 1024 or unit == "TiB":
            return "%.1f %s" % (n, unit) if unit != "B" else "%d B" % n
        n /= 1024.0
    return "%d" % n


def remove(cand: Candidate) -> int:
    """Remove one candidate. Returns bytes actually removed (best effort)."""
    before = _du_bytes(cand.path)
    try:
        if os.path.isdir(cand.path) and not os.path.islink(cand.path):
            shutil.rmtree(cand.path)
        else:
            os.unlink(cand.path)
    except OSError as exc:
        print("  ! could not remove %s: %s" % (cand.path, exc), file=sys.stderr)
        return 0
    return before


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Reclaim disk from re-downloadable caches, gated and allowlisted.",
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("--apply", action="store_true",
                    help="actually remove (default is a dry run, which removes nothing)")
    ap.add_argument("--dry-run", action="store_true", help="explicit dry run (the default)")
    ap.add_argument("--yes", action="store_true", help="required for --apply")
    ap.add_argument("--json", action="store_true", help="machine-readable report")
    ap.add_argument("--gate-free-pct", type=float, default=GATE_FREE_PCT_DEFAULT,
                    help="only act when / usage is at or above this percent (default %.0f)"
                         % GATE_FREE_PCT_DEFAULT)
    ap.add_argument("--min-bytes", type=int, default=MIN_BYTES_DEFAULT,
                    help="only act when at least this many bytes are reclaimable")
    ap.add_argument("--min-age-seconds", type=int, default=MIN_AGE_SECONDS_DEFAULT,
                    help="skip candidates touched more recently than this")
    ap.add_argument("--fingerprint", action="store_true",
                    help="print the protected-path fingerprint and exit")
    ap.add_argument("--selftest", action="store_true",
                    help="run the self-test on a throwaway tree and exit")
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest()

    if args.fingerprint:
        print(json.dumps(fingerprint(), indent=2))
        return 0

    apply = args.apply and not args.dry_run

    before_fp = fingerprint()
    used_pct, free, total = free_pct_root()

    cands = collect(args.min_age_seconds)
    overlaps = [c for c in cands if c.overlap]
    clean = [c for c in cands if not c.overlap]
    reclaimable = sum(c.bytes for c in clean)

    # A candidate overlapping a protected path is a BUG in the allowlist, not a
    # thing to skip quietly. Refuse the whole run.
    if overlaps:
        print("REFUSED: %d candidate(s) resolve inside a protected path:" % len(overlaps),
              file=sys.stderr)
        for c in overlaps:
            print("  %s  (protected by %s)" % (c.path, c.overlap), file=sys.stderr)
        return 2

    classes: dict[str, dict] = {}
    for c in clean:
        bucket = classes.setdefault(c.kind, {"entries": 0, "bytes": 0})
        bucket["entries"] += c.count
        bucket["bytes"] += c.bytes

    report = {
        "version": VERSION,
        "mode": "apply" if apply else "dry-run",
        "acted": False,
        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "root": {"used_pct": round(used_pct, 2), "free_bytes": free, "total_bytes": total,
                 "gate_free_pct": args.gate_free_pct},
        "reclaimable_bytes": reclaimable,
        "classes": {k: v for k, v in sorted(classes.items())},
        "candidates": [c.as_dict() for c in sorted(clean, key=lambda c: -c.bytes)],
        "protected": {"patterns": PROTECTED_PATTERNS, "overlaps": len(overlaps)},
        "fingerprint_before": before_fp,
    }

    if apply:
        refusals = []
        if not args.yes:
            refusals.append("--apply without --yes")
        if used_pct < args.gate_free_pct:
            refusals.append("/ at %.1f%% is below the %.1f%% gate"
                            % (used_pct, args.gate_free_pct))
        if reclaimable < args.min_bytes:
            refusals.append("only %s reclaimable, below the %s floor"
                            % (human(reclaimable), human(args.min_bytes)))
        if refusals:
            report["refused"] = refusals
            if args.json:
                print(json.dumps(report, indent=2))
            else:
                print("REFUSED (nothing removed):")
                for r in refusals:
                    print("  - %s" % r)
            return 2

        freed = 0
        for c in sorted(clean, key=lambda c: -c.bytes):
            freed += remove(c)
        report["acted"] = True
        report["freed_bytes"] = freed
        report["root_after"] = {"used_pct": round(free_pct_root()[0], 2),
                                "free_bytes": free_pct_root()[1]}

    report["fingerprint_after"] = fingerprint()

    # The dry run must be provably inert: the protected set is intact.
    #
    # mtime/size are RECORDED as evidence but deliberately excluded from this
    # predicate. /root/authority.db is a LIVE SQLite file that company-api
    # writes continuously, and a directory's mtime moves whenever anything
    # inside it is touched -- measured 2026-10-14T01:21Z: the DB grew 20 MB
    # during a 32 s dry run with no help from this tool. Comparing mtime would
    # therefore report "changed" on every honest run and train the reader to
    # ignore it. What this predicate DOES catch is what a purge could actually
    # do: delete a path (exists/inode), replace it (inode), or alter a static
    # file's content (sha256). /opt/company is checked through git.
    integrity_keys = ("path", "exists", "inode", "sha256", "sha256_bytes")

    def _integrity(fp):
        return [{k: e.get(k) for k in integrity_keys} for e in fp["paths"]]

    def _same(a, b):
        return (_integrity(a) == _integrity(b)
                and a.get("opt_company_git") == b.get("opt_company_git"))

    same = _same(report["fingerprint_before"], report["fingerprint_after"])
    report["protected_intact"] = same
    report["protected_unchanged"] = same  # kept for older readers

    # If it is not intact, say exactly which path and which field -- an
    # unexplained "NO" is the thing that trains a reader to ignore the check.
    if not same:
        mismatched = []
        for b, a in zip(report["fingerprint_before"]["paths"],
                        report["fingerprint_after"]["paths"]):
            bv = {k: b.get(k) for k in integrity_keys}
            av = {k: a.get(k) for k in integrity_keys}
            if bv != av:
                mismatched.append({"path": a["path"], "before": bv, "after": av})
        if (report["fingerprint_before"].get("opt_company_git")
                != report["fingerprint_after"].get("opt_company_git")):
            mismatched.append({"path": "/opt/company (git identity)",
                               "before": report["fingerprint_before"].get("opt_company_git"),
                               "after": report["fingerprint_after"].get("opt_company_git")})
        report["protected_mismatched"] = mismatched

    # Name the live paths whose size/mtime legitimately moved, so a "mtime
    # changed" reading is never mistaken for interference.
    volatile = []
    before_by_path = {e["path"]: e for e in report["fingerprint_before"]["paths"]}
    for e in report["fingerprint_after"]["paths"]:
        b = before_by_path.get(e["path"])
        if b and (b.get("size") != e.get("size") or b.get("mtime_ns") != e.get("mtime_ns")):
            volatile.append({"path": e["path"], "size_before": b.get("size"),
                             "size_after": e.get("size"),
                             "inode_before": b.get("inode"), "inode_after": e.get("inode")})
    report["protected_volatile"] = volatile

    if args.json:
        print(json.dumps(report, indent=2))
        return 0

    print("disk-reclaim v%s  mode=%s  host=%s" % (VERSION, report["mode"], os.uname().nodename))
    print("  /            %.1f%% used, %s free of %s  (gate %.0f%%)"
          % (used_pct, human(free), human(total), args.gate_free_pct))
    print("  reclaimable  %s  in %d candidate(s)" % (human(reclaimable), len(clean)))
    for kind, b in sorted(report["classes"].items(), key=lambda kv: -kv[1]["bytes"]):
        print("    %-28s %10s  %d entr(ies)" % (kind, human(b["bytes"]), b["entries"]))
    print("  protected    %d pattern(s), %d overlap(s)  -> %s"
          % (len(PROTECTED_PATTERNS), len(overlaps), "CLEAN" if not overlaps else "REFUSED"))
    if report.get("protected_volatile"):
        print("  live paths   %d moved size/mtime during the run (their own service writes "
              "them; inode and git identity unchanged)" % len(report["protected_volatile"]))
    if apply:
        if report.get("acted"):
            print("  ACTED        freed %s; / now %.1f%%"
                  % (human(report.get("freed_bytes", 0)), report["root_after"]["used_pct"]))
            for c in sorted(clean, key=lambda c: -c.bytes)[:10]:
                print("    removed %s" % c.path)
        else:
            print("  REFUSED      nothing removed:")
            for r in report.get("refused", []):
                print("    - %s" % r)
    else:
        print("  DRY RUN      nothing removed; top candidates:")
        for c in sorted(clean, key=lambda c: -c.bytes)[:10]:
            print("    %10s  %s" % (human(c.bytes), c.path))
        print("  protected paths intact: %s" % ("YES" if same else "NO"))
        if not same:
            for m in report.get("protected_mismatched", []):
                print("    MISMATCH %s" % m["path"])
                print("      before %s" % m["before"])
                print("      after  %s" % m["after"])
            return 3
        if reclaimable < args.min_bytes:
            print("  NOTE         reclaimable (%s) is below the %s floor, so --apply "
                  "would refuse" % (human(reclaimable), human(args.min_bytes)))
    return 0


# ---------------------------------------------------------------------------

def selftest() -> int:
    """Prove the two things that matter, on a throwaway tree."""
    import contextlib
    import hashlib
    import io
    import tempfile

    global SCAN_ROOTS, DEV_JS_ROOTS, DOWNLOAD_CACHES, PROTECTED_PATTERNS

    with tempfile.TemporaryDirectory(prefix="disk-reclaim-selftest-") as tmp:
        # a planted cache, and a planted "protected" tree that must survive
        cache = os.path.join(tmp, "cache", "__pycache__")
        prot = os.path.join(tmp, "protected-tree")
        keep = os.path.join(tmp, "authority.db")
        os.makedirs(cache)
        os.makedirs(os.path.join(prot, "cache"))
        with open(os.path.join(cache, "x.pyc"), "wb") as fh:
            fh.write(b"P" * 4096)
        with open(os.path.join(prot, "cache", "y.bin"), "wb") as fh:
            fh.write(b"Q" * 4096)
        with open(keep, "wb") as fh:
            fh.write(b"PRECIOUS" * 1024)

        # 1. the planted bytecode is discovered, with real bytes attributed
        SCAN_ROOTS = [os.path.join(tmp, "cache")]
        DEV_JS_ROOTS = []
        DOWNLOAD_CACHES = []
        PROTECTED_PATTERNS = [keep, keep + "*"]
        found = collect(0)
        got = sum(c.bytes for c in found)
        if got <= 0 or not any(c.path == cache for c in found):
            print("SELFTEST FAIL: planted __pycache__ not discovered (got %d bytes)" % got)
            return 1
        print("SELFTEST ok: discovered planted bytecode (%d bytes)" % got)

        # 2. an allowlist entry that points INSIDE a protected tree is REFUSED
        #    (this is the guard against a bad allowlist, so it must be reachable)
        DOWNLOAD_CACHES = [(os.path.join(prot, "cache"), "planted-bad-entry")]
        PROTECTED_PATTERNS = [prot, prot + "/*"]
        flagged = [c for c in collect(0) if c.overlap is not None]
        if not any(c.path == os.path.join(prot, "cache") for c in flagged):
            print("SELFTEST FAIL: protected overlap was not detected")
            return 1
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            rc = main(["--dry-run", "--min-age-seconds", "0"])
        if rc != 2 or not os.path.exists(os.path.join(prot, "cache", "y.bin")):
            print("SELFTEST FAIL: protected overlap did not refuse (rc=%s)" % rc)
            return 1
        print("SELFTEST ok: protected overlap detected and refused with exit 2")

        # 3. a dry run removes nothing and leaves the protected file identical
        DOWNLOAD_CACHES = []
        PROTECTED_PATTERNS = [keep, keep + "*"]
        SCAN_ROOTS = [os.path.join(tmp, "cache")]
        before = hashlib.sha256(open(keep, "rb").read()).hexdigest()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = main(["--dry-run", "--json", "--min-age-seconds", "0", "--min-bytes", "1"])
        after = hashlib.sha256(open(keep, "rb").read()).hexdigest()
        if rc != 0 or before != after or not os.path.exists(cache):
            print("SELFTEST FAIL: dry run was not inert (rc=%s, kept=%s, cache_still=%s)"
                  % (rc, before == after, os.path.exists(cache)))
            return 1
        print("SELFTEST ok: dry run removed nothing and left the protected file identical")

        # 4. the gates refuse an under-pressure-less disk
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = main(["--apply", "--yes", "--gate-free-pct", "99.9",
                       "--min-bytes", "1", "--min-age-seconds", "0"])
        if rc != 2 or not os.path.exists(cache):
            print("SELFTEST FAIL: the free-space gate did not refuse (rc=%s)" % rc)
            return 1
        print("SELFTEST ok: --apply refused by the free-space gate (exit 2)")
    print("SELFTEST PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())

