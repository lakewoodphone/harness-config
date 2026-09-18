#!/usr/bin/env python3
"""Install the search-index refresh as a scheduled job. Windows or Linux.

WHY. Building the index was the easy half. The fleet's most expensive habit is a
thing that runs, stops working, and looks healthy (L160, L167, P51) — so the
refresh has to be *scheduled* and *checked*, not left to whoever remembers.

On Windows it registers a per-user Scheduled Task (no admin needed, and the
elevated-engine mess from `dshw` is avoided entirely). On Linux it writes a cron
line. Both run the same `refresh.py`.

USAGE
  install-refresh.py --install            # register hourly
  install-refresh.py --install --minutes 30
  install-refresh.py --uninstall
  install-refresh.py --status
"""
from __future__ import annotations

import argparse
import os
import platform
import subprocess
import sys

HOME = os.path.expanduser("~")
FSEARCH = os.path.join(HOME, ".fsearch")
REFRESH = os.path.join(FSEARCH, "refresh.py")
LOG = os.path.join(FSEARCH, "refresh.log")
TASK = "DSH search index refresh"
CRON_TAG = "# fsearch-refresh"


def python_exe() -> str:
    return sys.executable or ("python" if platform.system() == "Windows" else "python3")


def windows_install(minutes: int) -> int:
    # `schtasks` runs the /TR string directly, NOT through a shell, so `>>` and
    # `2>&1` are passed as literal arguments and the task fails. Wrapping in
    # `cmd /c` is what makes redirection work -- verified by reading back the
    # registered command, which showed the raw `>>` before this change.
    inner = f'"{python_exe()}" "{REFRESH}" >> "{LOG}" 2>&1'
    cmd = f'cmd /c {inner}'
    args = ["schtasks", "/Create", "/TN", TASK, "/SC", "MINUTE",
            "/MO", str(minutes), "/TR", cmd, "/F"]
    p = subprocess.run(args, capture_output=True, text=True)
    sys.stdout.write((p.stdout or "") + (p.stderr or ""))
    if p.returncode == 0:
        print(f"registered: '{TASK}' every {minutes} min")
        print("  verify: schtasks /Query /TN \"" + TASK + "\" /FO LIST /V "
              "| findstr /i \"Task To Run Status\"")
    return p.returncode


def windows_uninstall() -> int:
    p = subprocess.run(["schtasks", "/Delete", "/TN", TASK, "/F"],
                       capture_output=True, text=True)
    sys.stdout.write((p.stdout or "") + (p.stderr or ""))
    return 0


def windows_status() -> int:
    p = subprocess.run(["schtasks", "/Query", "/TN", TASK, "/FO", "LIST", "/V"],
                       capture_output=True, text=True)
    out = (p.stdout or "") + (p.stderr or "")
    if p.returncode != 0:
        print("not registered")
        return 1
    for line in out.splitlines():
        low = line.lower()
        if any(k in low for k in ("taskname", "status", "last run", "last result",
                                  "next run", "schedule")):
            print("  " + line.strip())
    return 0


def linux_install(minutes: int) -> int:
    line = (f"*/{minutes} * * * * {python_exe()} {REFRESH} >> {LOG} 2>&1 {CRON_TAG}")
    cur = subprocess.run(["crontab", "-l"], capture_output=True, text=True).stdout or ""
    kept = [l for l in cur.splitlines() if CRON_TAG not in l]
    kept.append(line)
    new = "\n".join(kept).strip() + "\n"
    p = subprocess.run(["crontab", "-"], input=new, capture_output=True, text=True)
    if p.returncode != 0:
        sys.stderr.write(p.stderr)
        return p.returncode
    print(f"installed cron line: {line}")
    return 0


def linux_uninstall() -> int:
    cur = subprocess.run(["crontab", "-l"], capture_output=True, text=True).stdout or ""
    kept = [l for l in cur.splitlines() if CRON_TAG not in l]
    subprocess.run(["crontab", "-"], input="\n".join(kept).strip() + "\n",
                   capture_output=True, text=True)
    print("removed the cron line")
    return 0


def linux_status() -> int:
    cur = subprocess.run(["crontab", "-l"], capture_output=True, text=True).stdout or ""
    hits = [l for l in cur.splitlines() if CRON_TAG in l]
    print("\n".join(hits) if hits else "not registered")
    return 0 if hits else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--install", action="store_true")
    ap.add_argument("--uninstall", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--minutes", type=int, default=60)
    a = ap.parse_args()

    if not os.path.exists(REFRESH):
        print(f"missing {REFRESH}; copy refresh.py there first", file=sys.stderr)
        return 1
    win = platform.system() == "Windows"
    if a.install:
        return windows_install(a.minutes) if win else linux_install(a.minutes)
    if a.uninstall:
        return windows_uninstall() if win else linux_uninstall()
    return windows_status() if win else linux_status()


if __name__ == "__main__":
    sys.exit(main())
