#!/usr/bin/env python3
"""Raise a wake flag from ANY machine.

The store and the dispatcher live on the authority, so a flag has to be filed
there. This is the one-liner that does it without anyone hand-building an ssh
command line (which is this repo's most repeated self-inflicted wound).

    python scripts/wake-flag.py --subject "sms-webhook-lost:2026-09-18" \
        --prompt "Fix the inbound write path against the deployed tree." \
        --kind sms-loss --source webhook-monitor --priority high

Reads the printed result: filed / deduped / suppressed:<reason> / capped.
`suppressed:error` means it did NOT file - treat that as a failure, never as quiet.

Stdlib only. Never sends anything to a human. See the `secretary-wake` skill.
"""
from __future__ import annotations

import argparse
import shlex
import shutil
import subprocess
import sys

HOSTS = ("secratary-ts", "secratary", "secretary-ts", "secretary")
# The prefix stays UNQUOTED so the remote shell expands ~, and only the arguments
# are quoted. Quoting the whole prefix makes it a single command name that does
# not exist.
REMOTE_PREFIX = "python3 ~/bin/wake.py flag"


def pick_host() -> str | None:
    for h in HOSTS:
        try:
            r = subprocess.run(
                ["ssh", "-o", "ConnectTimeout=8", "-o", "BatchMode=yes", h, "echo ok"],
                capture_output=True, text=True, timeout=25,
            )
            if r.returncode == 0 and "ok" in r.stdout:
                return h
        except Exception:
            continue
    return None


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--subject", required=True, help="stable dedup key, e.g. thing:date")
    p.add_argument("--prompt", required=True, help="what the woken session must do")
    p.add_argument("--kind", default="task")
    p.add_argument("--source", default="manual")
    p.add_argument("--priority", default="normal", choices=["high", "normal", "low"])
    p.add_argument("--context", default="")
    p.add_argument("--host", default=None)
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args()

    args = ["--subject", a.subject,
            "--prompt", a.prompt,
            "--kind", a.kind,
            "--source", a.source,
            "--priority", a.priority]
    if a.context:
        args += ["--context", a.context]
    remote_cmd = REMOTE_PREFIX + " " + " ".join(shlex.quote(x) for x in args)

    host = a.host or pick_host()
    if not host:
        print("could not reach the authority on any known host alias "
              f"({', '.join(HOSTS)}); nothing was filed", file=sys.stderr)
        return 2
    if a.dry_run:
        print(f"would run on {host}:\n  {remote_cmd}")
        return 0

    r = subprocess.run(["ssh", "-o", "ConnectTimeout=10", "-o", "BatchMode=yes",
                        host, remote_cmd], capture_output=True, text=True, timeout=120)
    out = (r.stdout or "").strip()
    err = (r.stderr or "").strip()
    print(out or "(no output)")
    if err:
        print(err, file=sys.stderr)
    if r.returncode != 0:
        print(f"ssh/remote exit {r.returncode} - the flag may NOT have been filed",
              file=sys.stderr)
        return 2
    if "suppressed:error" in out:
        print("REFUSED: the store returned an error, so nothing was filed. "
              "This is a failure, not quiet.", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
