#!/usr/bin/env python3
"""Install the journal-ceiling-refresh cron job, proving the line before it is written.

WHY A SCRIPT. This line was attempted three times and crontab refused each time with
"command too long", because the payload that arrived was not the payload that was sent: a shell
here-string turned one long base64 token into a multi-line argument, and the replacement line was
built by string concatenation across a newline. Each failure was silent about the cause.

So this installer refuses to write anything unless it can prove, first, that the line it is about
to install is short enough, and second, that the command inside it actually runs and exits 0.

Usage:
    install-ceiling-cron.py <base64-of-the-command>

It reads the CURRENT crontab, replaces every `journal-ceiling-refresh` job line with exactly one
copy of the new one, refuses if any line would exceed crontab's limit, installs via stdin, then
reads the crontab back and decodes the line to show what is really there.
"""
from __future__ import annotations

import base64
import subprocess
import sys

CRON_MAX_LINE = 998
WRAPPER = "/usr/local/bin/cron-wrap.sh journal-ceiling-refresh"


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    payload = sys.argv[1].strip()
    # A base64 token has no whitespace. If it has any, something upstream wrapped it and the
    # line would be built from a mangled argument -- which is exactly how the first three
    # attempts failed. Refuse rather than install a command that cannot work.
    if any(c.isspace() for c in payload):
        print("REFUSING: the payload contains whitespace, so it was wrapped in transit.")
        print(f"  payload length={len(payload)}  first 80={payload[:80]!r}")
        return 3
    try:
        decoded = base64.b64decode(payload).decode()
    except Exception as exc:
        print(f"REFUSING: the payload is not valid base64: {exc}")
        return 3

    line = f"*/15 * * * * {WRAPPER} {payload}"
    print(f"decoded command      : {decoded}")
    print(f"replacement line len : {len(line)}")
    if len(line) > CRON_MAX_LINE:
        print(f"REFUSING: line exceeds crontab's {CRON_MAX_LINE}-character limit")
        return 3

    # Prove the command itself works before scheduling it. This is the rule that a previous
    # session learned the hard way: a python -c inside a double-quoted arg returned rc=1 and
    # would have failed silently every 15 minutes forever.
    probe = subprocess.run(["bash", "-lc", decoded + " ; echo PROBE_RC=$?"],
                           capture_output=True, text=True, timeout=300)
    tail = (probe.stdout or "").strip().splitlines()[-1:] or ["(no output)"]
    print(f"probe of the command : {tail[0]}")
    if "PROBE_RC=0" not in (probe.stdout or ""):
        print("REFUSING: the command does not exit 0, so scheduling it would fail silently.")
        print((probe.stdout or "")[-2000:])
        print((probe.stderr or "")[-1000:])
        return 3

    cur = subprocess.run(["crontab", "-l"], capture_output=True, text=True).stdout
    out, kept = [], 0
    for ln in cur.splitlines():
        if "journal-ceiling-refresh" in ln and not ln.lstrip().startswith("#"):
            if kept == 0:
                out.append(line)
                kept += 1
            continue
        out.append(ln)
    if kept == 0:
        out.append(line)

    jobs = [l for l in out if "journal-ceiling-refresh" in l and not l.lstrip().startswith("#")]
    longest = max((len(l) for l in out), default=0)
    print(f"job lines after edit : {len(jobs)}   longest line in crontab: {longest}")
    if len(jobs) != 1 or longest > CRON_MAX_LINE:
        print("REFUSING: the crontab would be invalid")
        return 3

    p = subprocess.run(["crontab", "-"], input="\n".join(out) + "\n",
                       capture_output=True, text=True)
    print(f"install rc           : {p.returncode} {p.stderr.strip()[:200]}")
    if p.returncode != 0:
        return 1

    verify = subprocess.run(["crontab", "-l"], capture_output=True, text=True).stdout
    shown = [l for l in verify.splitlines() if "ceiling-refresh" in l]
    for l in shown:
        print(f"installed len {len(l)} : {l[:100]}...")
        print(f"decodes to     : {base64.b64decode(l.split()[-1]).decode()}")
    print("OK" if len(shown) == 1 else f"WARNING: {len(shown)} job lines present")
    return 0


if __name__ == "__main__":
    sys.exit(main())
