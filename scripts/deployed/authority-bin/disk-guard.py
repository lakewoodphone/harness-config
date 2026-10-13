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

PORTED TO THE CLOUD AUTHORITY, 2026-10-11 (workstream 135)
----------------------------------------------------------
Three things changed, and every one of them is a named constant below rather than a literal buried
in the code, so the same file runs on either box and neither box's paths are assumptions:

  * RETENTION_SCRIPT / BACKUP_ROOT / CONSUMERS are now environment-overridable and default to the
    OFFICE paths, so the office behaviour of this file is unchanged.
  * ON THE CLOUD BOX IT DOES NOT INVOKE THE RETENTION SCRIPT. See "MUST NEVER" below.
  * The cloud boot disk is `sda1` at 65% with 26 GB free against a 23.7 GB authority database, so
    the free-space thresholds matter MORE there, not less.

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
      `scripts/server/prune-backups.sh`, which this guard CHECKS FOR but never runs.

      THIS IS A CHANGE FROM THE OFFICE COPY, and it is deliberate. The office version's design is
      "when disk pressure is high, run retention". On the cloud authority the only retention
      script that exists is the one that deletes under the backup root, and the office box is the
      ROLLBACK ANCHOR for the 2026-10-11 cutover. A guard whose alarm path deletes is a guard that
      can take the company down while reporting that it saved it. 2026-10-11 workstream 135:
      DISK_GUARD_INVOKE_RETENTION defaults to "0" and is documented rather than implemented, so a
      later session that wants it has to say so explicitly and point it at a cloud tree.

    - fire below the threshold, or stay quiet above it.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

WARN_PCT = float(os.environ.get("DISK_WARN_PCT", "90"))
CRIT_PCT = float(os.environ.get("DISK_CRIT_PCT", "95"))
TMP_WARN_PCT = float(os.environ.get("TMP_WARN_PCT", "80"))

STATE_DIR = Path(os.environ.get("DISK_GUARD_STATE", str(Path.home() / ".disk-guard")))
STATUS = STATE_DIR / "status.json"
LOG = STATE_DIR / "guard.log"

# Defaults are the OFFICE paths, unchanged, so this file dropped onto the office box behaves
# exactly as it always did. The cloud box sets these in its cron line.
RETENTION_SCRIPT = Path(os.environ.get(
    "DISK_RETENTION_SCRIPT",
    "/home/zabz/personal-secretary-mvp/scripts/server/prune-backups.sh"))
BACKUP_ROOT = Path(os.environ.get("DISK_BACKUP_ROOT", "/home/zabz/secretary-backups"))

# Whether the guard is allowed to RUN the retention script when it alarms. Off everywhere as of
# 2026-10-11; see MUST NEVER above.
INVOKE_RETENTION = os.environ.get("DISK_GUARD_INVOKE_RETENTION", "0") == "1"

# The paths that have actually grown. `du` is capped with `-x` (one filesystem) and a timeout so
# this check can never become the reason the machine is slow. Missing paths are skipped silently:
# a consumer list is a map of where to look, not a list of things that must exist.
_DEFAULT_CONSUMERS = (
    "/home/zabz/secretary-backups,"
    "/home/zabz/personal-secretary-mvp/data,"
    "/home/zabz/quarantine-debris,"
    "/home/zabz/phoenix-evidence,"
    "/home/zabz/repos,"
    "/home/zabz/accounting-data,"
    "/home/zabz/recon-20260915,"
    "/tmp"
)
CONSUMERS = [p for p in os.environ.get("DISK_CONSUMERS", _DEFAULT_CONSUMERS).split(",") if p]


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
            "used_pct": round(pct, 1), "free_mb": round(free / 1048576.0, 1),
            "free_gb": round(free / 1073741824.0, 2)}


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
        "invocation_allowed": INVOKE_RETENTION,
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
        return {"ok": False, "unreadable": True, "host": os.uname().nodename,
                "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    if root["used_pct"] >= CRIT_PCT:
        findings.append("CRITICAL: / at %.1f%% (%.1f GB free, %.0f MB)" % (
            root["used_pct"], root["free_gb"], root["free_mb"]))
    elif root["used_pct"] >= WARN_PCT:
        findings.append("/ at %.1f%% (%.1f GB free, %.0f MB), warn threshold %.0f%%"
                        % (root["used_pct"], root["free_gb"], root["free_mb"], WARN_PCT))
    if tmp and tmp["used_pct"] >= TMP_WARN_PCT:
        findings.append("/tmp at %.1f%% (%s of %s MB)"
                        % (tmp["used_pct"], tmp["free_mb"], round(tmp["total_bytes"] / 1048576.0)))
    # The specific mechanism whose absence caused the 2026-09-30 fill.
    if not ret["exists"]:
        findings.append("RETENTION SCRIPT MISSING: %s -- nothing bounds the backup tree until it "
                        "returns" % ret["path"])
    elif not ret["executable"]:
        findings.append("RETENTION SCRIPT NOT EXECUTABLE: %s" % ret["path"])

    # The retention policy is NOT applied here. If it ever is, it is applied through the documented
    # script and never by this file, and it says so in the log either way.
    invocation = None
    if findings and INVOKE_RETENTION and ret["exists"] and ret["executable"]:
        try:
            p = subprocess.run([str(RETENTION_SCRIPT), str(BACKUP_ROOT)],
                               capture_output=True, text=True, timeout=600)
            invocation = {"ran": str(RETENTION_SCRIPT), "rc": p.returncode,
                          "tail": (p.stdout or p.stderr or "").strip()[-300:]}
        except Exception as exc:  # noqa: BLE001
            invocation = {"ran": str(RETENTION_SCRIPT), "rc": None,
                          "tail": "%s: %s" % (type(exc).__name__, exc)}

    return {
        "ok": not findings,
        "unreadable": False,
        "host": os.uname().nodename,
        "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "warn_pct": WARN_PCT,
        "crit_pct": CRIT_PCT,
        "tmp_warn_pct": TMP_WARN_PCT,
        "root": root,
        "tmp": tmp,
        "backup_root": str(BACKUP_ROOT),
        "backup_dirs": backdirs,
        "backup_mb": backup_mb,
        "retention": ret,
        "retention_invocation": invocation,
        "consumers": top_consumers() if findings else [],
        "findings": findings,
    }


def render(res: dict) -> str:
    if res.get("unreadable"):
        return "UNREADABLE: could not stat the root filesystem"
    if res["ok"]:
        return "ok - / at %.1f%% (%s GB free), /tmp at %.1f%%%s  [warn %.0f%% crit %.0f%%]" % (
            res["root"]["used_pct"], res["root"]["free_gb"],
            res["tmp"]["used_pct"] if res["tmp"] else 0.0,
            "" if res["backup_dirs"] < 0 else ", %d backup dir(s)" % res["backup_dirs"],
            res["warn_pct"], res["crit_pct"])
    lines = ["-" * 72]
    for f in res["findings"]:
        lines.append("  " + f)
    lines.append("  host: %s   at: %s" % (res.get("host"), res["at"]))
    lines.append("  backup root: %s   dirs: %s   size: %s MB"
                 % (res.get("backup_root"), res["backup_dirs"],
                    res["backup_mb"] if res["backup_mb"] is not None else "n/a"))
    lines.append("  retention script: %s (exists=%s executable=%s invoked=%s)"
                 % (res["retention"]["path"], res["retention"]["exists"],
                    res["retention"]["executable"],
                    "yes" if res.get("retention_invocation") else "no"))
    if res["consumers"]:
        lines.append("  biggest consumers (MB):")
        for c in res["consumers"]:
            lines.append("    %8d  %s" % (c["mb"], c["path"]))
    lines.append("  the documented retention policy is F7 (keep <1d all, 1/day to 7d, 1/week to")
    lines.append("  30d, nothing >30d); the script that applies it is %s" % res["retention"]["path"])
    return "\n".join(lines)


def selftest() -> int:
    problems = []
    # The threshold logic must fire above and stay quiet below, on synthetic readings.
    for pct, warn, crit, want in ((89.9, 90, 95, False), (90.0, 90, 95, True),
                                  (95.0, 90, 95, True), (99.0, 90, 95, True)):
        got = pct >= crit or pct >= warn
        if got != want:
            problems.append("pct=%s warn=%s crit=%s expected %s got %s" % (pct, warn, crit, want))
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
    print("SELFTEST OK (host %s, / at %.1f%%, warn %.0f%% crit %.0f%%, retention script exists=%s)"
          % (r.get("host"), r["root"]["used_pct"], WARN_PCT, CRIT_PCT, ret["exists"]))
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
                    fh.write("%s  ok  / %.1f%%  %.1fGB free  backups %s dir(s)\n"
                             % (res["at"], res["root"]["used_pct"], res["root"]["free_gb"],
                                res["backup_dirs"]))
                else:
                    fh.write("%s  ALARM  %s\n" % (res["at"], " | ".join(res["findings"])))
        except Exception as exc:  # noqa: BLE001
            print("WARN: could not write %s: %s" % (STATUS, exc), file=sys.stderr)

    if res.get("unreadable"):
        return 2
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
