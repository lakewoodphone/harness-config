#!/usr/bin/env python3
"""Close a pull request without merging, leaving the branch intact.  pr-close.py <number>"""
import json
import sys
import urllib.error
import urllib.request

TOK = open("/root/.git-credentials", encoding="utf-8").read().strip().split(":", 2)[2].split("@", 1)[0]
REPO = "lakewoodphone/phone-and-tech-full"


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: pr-close.py <number>")
        return 2
    req = urllib.request.Request(
        "https://api.github.com/repos/%s/pulls/%s" % (REPO, sys.argv[1]),
        data=json.dumps({"state": "closed"}).encode(), method="PATCH",
        headers={"Authorization": "Bearer " + TOK, "Accept": "application/vnd.github+json",
                 "User-Agent": "prclose", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            print("closed:", resp.status)
            return 0
    except urllib.error.HTTPError as exc:
        print("failed:", exc.code, (exc.read() or b"").decode()[:150])
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
