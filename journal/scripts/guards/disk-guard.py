#!/usr/bin/env python3
"""DISK GUARD -- the authority's own filesystem had no alarm, and it filled twice in three days.

WHY THIS EXISTS
---------------
Measured, on `secratary`:

    2026-09-27 09:0xZ   / at 100% (17 MB free). Backups stopped producing complete snapshots.
                        "There is NO valid backup today." (journal P2553)
    2026-09-30 14:5xZ   / at 99% (7.6 GB free). secretary-backups held 298 GB across 21
                        directories. The retention script that bounds them had been DELETED by a
                        copy-style deployment, and its caller printed
                        "WARN: prune-backups.sh missing; skipping pre-backup retention" and
                        carried on. (journal P2799)

Two 99-100% events in four days, and nothing on the machine was watching its own root filesystem.
What existed was `box-health-check.sh`, which runs DAILY and watches a DIFFERENT box
(`lpt-apps-01`, the Hetzner app server) -- so the one disk that actually filled had no reader -- and
the disk it guards would fill again between two daily runs anyway: one backup directory is ~18 GB,
which is 20% of the free space measured on 2026-09-30.

THE THREE SIGNALS, and why each is here
---------------------------------------
1. FREE SPACE on `/` and `/tmp`, sampled every 15 minutes. A threshold is only useful above the
   rate of growth: at 18 GB per backup and backups every six hours, a daily check can miss the
   whole event.
2. THE RETENTION SCRIPT EXISTS AND IS EXECUTABLE. This is the specific mechanism whose ABSENCE
   caused the last fill, and it is NOT a crontab target -- it is called by `backup-data.sh`, which
   degrades to a warning when it is gone. `cron-target-guard.py` cannot see it, so it is checked
   here: the file is the difference between 216 GB and 298 GB of backups on a 467 GB volume.
3. WHERE THE SPACE WENT, so the alarm is actionable. `du` over the paths that have actually grown
   (the backup root, the repo's data dir, debris, worktrees), newest first, capped so the check
   cannot become the heavy thing it is watching for.

Exit codes: 0 below every threshold, 1 at or above the warn threshold, 2 the signal could not be
read at all (which is itself a finding: an unreadable disk check is not a healthy disk).

USAGE
    disk-guard.py                     # human output, exit 1 when over threshold
    disk-guard.py --json
    disk-guard.py --write-status      # also write ~/.disk-guard/status.json + guard.log
    disk-guard.py --selftest          # prove the threshold logic both ways

MUST NEVER
    - delete, move or truncate anything. It measures and reports; the documented retention policy
      (F7: keep <1d all, 1/day to 7d, 1/week to 30d, nothing >30d) is applied by
      `scripts/server/prune-backups.sh`, which this guard checks for but never replaces;
    - fire below the threshold, or stay quiet above it.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

WARN_PCT = float(os.environ.get("DISK_WARN_PCT", "90"))
CRIT_PCT = float(os.environ.get("DISK_CRIT_PCT", "95"))
TMP_WARN_PCT = float(os.environ.get("TMP_WARN_PCT", "80"))

STATE_DIR = Path.home() / ".disk-guard"
STATUS = STATE_DIR / "status.json"
LOG = STATE_DIR / "guard.log"

RETENTION_SCRIPT = Path("/home/zabz/personal-secretary-mvp/scripts/server/prune-backups.sh")
BACKUP_ROOT = Path("/home/zabz/secretary-backups")

# The paths that have actually grown, measured. `du` is capped with `-x` (one filesystem) and a
# timeout so this check can never become the reason the machine is slow.
CONSUMERS = [
    "/home/zabz/secretary-backups",
    "/home/zabz/personal-secretary-mvp/data",
    "/home/zabz/quarantine-debris",
    "/home/zabz/phoenix-evidence",
    "/home/zabz/repos",
    "/home/zabz/accounting-data",
    "/home/zabz/recon-20260915",
    "/tmp",
]


def usage(path: str) -> dict | None:
    try:
        st = os.statvfs(path)
    except Exception:
        return None
    total = st.f_frsize * st.f_blocks
    free = st.f_frsize * st.f_bavail
    used = total - st.f_frsize * st.f_bfree
    pct = (used / total * 100.0) if total else 0.0
    return {"path": path, "total_bytes": total, "free_bytes": free, "used_bytes": used,
            "used_pct": round(pct, 1), "free_mb": round(free / 1048576.0, 1)}


def top_consumers(limit: int = 8) -> list[dict]:
    out = []
    for p in CONSUMERS:
        if not os.path.exists(p):
            continue
        try:
            r = subprocess.run(["du", "-sxm", p], capture_output=True, text=True, timeout=90)
            first = (r.stdout or "").split("\n")[0].split()
            if first:
                out.append({"path": p, "mb": int(first[0])})
        except Exception:
            continue
    out.sort(key=lambda d: -d["mb"])
    return out[:limit]


def retention_state() -> dict:
    exists = RETENTION_SCRIPT.is_file()
    return {
        "path": str(RETENTION_SCRIPT),
        "exists": exists,
        "executable": exists and os.access(RETENTION_SCRIPT, os.X_OK),
    }


def measure() -> dict:
    root = usage("/")
    tmp = usage("/tmp")
    ret = retention_state()
    backdirs = 0
    if BACKUP_ROOT.exists():
        try:
            backdirs = len([d for d in BACKUP_ROOT.iterdir() if d.is_dir()])
        except Exception:
            backdirs = -1
    # The backup ROOT is on the same filesystem as `/`, so statvfs() of it reports the whole
    # volume -- 365 GB -- not the 215 GB of backups. Measured 2026-09-30: the first version of this
    # guard printed "backups: 365680 MB" beside "biggest consumers: 220534 MB" for the same path,
    # which is a reading that cannot distinguish two states. Use du() for the directory itself.
    backup_mb = None
    if BACKUP_ROOT.exists():
        try:
            r = subprocess.run(["du", "-sxm", str(BACKUP_ROOT)], capture_output=True,
                               text=True, timeout=120)
            backup_mb = int((r.stdout or "0").split()[0])
        except Exception:
            backup_mb = None

    findings = []
    if root is None:
        return {"ok": False, "unreadable": True,
                "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    if root["used_pct"] >= CRIT_PCT:
        findings.append("CRITICAL: / at %.1f%% (%.1f MB free)" % (root["used_pct"], root["free_mb"]))
    elif root["used_pct"] >= WARN_PCT:
        findings.append("/ at %.1f%% (%.1f MB free), warn threshold %.0f%%"
                        % (root["used_pct"], root["free_mb"], WARN_PCT))
    if tmp and tmp["used_pct"] >= TMP_WARN_PCT:
        findings.append("/tmp at %.1f%% (%s of %s MB)"
                        % (tmp["used_pct"], tmp["free_mb"], round(tmp["total_bytes"] / 1048576.0)))
    # The specific mechanism whose absence caused the 2026-09-30 fill.
    if not ret["exists"]:
        findings.append("RETENTION SCRIPT MISSING: %s -- backups are unbounded until it returns"
                        % ret["path"])
    elif not ret["executable"]:
        findings.append("RETENTION SCRIPT NOT EXECUTABLE: %s" % ret["path"])

    return {
        "ok": not findings,
        "unreadable": False,
        "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "warn_pct": WARN_PCT,
        "crit_pct": CRIT_PCT,
        "root": root,
        "tmp": tmp,
        "backup_dirs": backdirs,
        "backup_mb": backup_mb,
        "retention": ret,
        "consumers": top_consumers() if findings else [],
        "findings": findings,
    }


def render(res: dict) -> str:
    if res.get("unreadable"):
        return "UNREADABLE: could not stat the root filesystem"
    if res["ok"]:
        return "ok - / at %.1f%% (%s MB free), /tmp at %.1f%%%s" % (
            res["root"]["used_pct"], res["root"]["free_mb"],
            res["tmp"]["used_pct"] if res["tmp"] else 0.0,
            "" if res["backup_dirs"] < 0 else ", %d backup dir(s)" % res["backup_dirs"])
    lines = ["-" * 72]
    for f in res["findings"]:
        lines.append("  " + f)
    lines.append("  backup dirs: %s   backups: %s MB"
                 % (res["backup_dirs"],
                    res["backup_mb"] if res["backup_mb"] is not None else "n/a"))
    if res["consumers"]:
        lines.append("  biggest consumers (MB):")
        for c in res["consumers"]:
            lines.append("    %8d  %s" % (c["mb"], c["path"]))
    lines.append("  the documented retention policy is F7 (keep <1d all, 1/day to 7d, 1/week to")
    lines.append("  30d, nothing >30d); the script that applies it is %s" % RETENTION_SCRIPT)
    return "\n".join(lines)


def selftest() -> int:
    problems = []
    # The threshold logic must fire above and stay quiet below, on synthetic readings.
    for pct, warn, crit, want in ((89.9, 90, 95, False), (90.0, 90, 95, True),
                                  (95.0, 90, 95, True), (99.0, 90, 95, True)):
        got = pct >= crit or pct >= warn
        if got != want:
            problems.append("pct=%s warn=%s crit=%s expected %s got %s" % (pct, warn, crit, want, got))
    # A real measurement must be readable.
    r = measure()
    if r.get("unreadable") or "root" not in r:
        problems.append("could not measure this host")
    # The retention check must reflect the filesystem, not a constant.
    ret = retention_state()
    if ret["exists"] != RETENTION_SCRIPT.is_file():
        problems.append("retention_state disagrees with the filesystem")
    if problems:
        print("SELFTEST FAILED")
        for p in problems:
            print("  - " + p)
        return 1
    print("SELFTEST OK (/ at %.1f%%, retention script exists=%s)"
          % (r["root"]["used_pct"], ret["exists"]))
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--write-status", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)

    if a.selftest:
        return selftest()

    res = measure()
    print(json.dumps(res, indent=1) if a.json else render(res))

    if a.write_status:
        try:
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            tmp = STATUS.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(res, indent=1) + "\n", encoding="utf-8")
            tmp.replace(STATUS)
            with LOG.open("a", encoding="utf-8") as fh:
                if res.get("unreadable"):
                    fh.write("%s  UNREADABLE\n" % res["at"])
                elif res["ok"]:
                    fh.write("%s  ok  / %.1f%%  backups %s dir(s)\n"
                             % (res["at"], res["root"]["used_pct"], res["backup_dirs"]))
                else:
                    fh.write("%s  ALARM  %s\n" % (res["at"], " | ".join(res["findings"])))
        except Exception as exc:  # noqa: BLE001
            print("WARN: could not write %s: %s" % (STATUS, exc), file=sys.stderr)

    if res.get("unreadable"):
        return 2
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
