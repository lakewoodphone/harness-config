#!/usr/bin/env python3
"""Comment on a pull request.  pr-comment.py <number> <body>   (body may be '-' to read stdin)"""
import json
import sys
import urllib.error
import urllib.request

TOK = open("/root/.git-credentials", encoding="utf-8").read().strip().split(":", 2)[2].split("@", 1)[0]
REPO = "lakewoodphone/phone-and-tech-full"


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: pr-comment.py <number> <body>")
        return 2
    body = sys.stdin.read() if sys.argv[2] == "-" else sys.argv[2]
    req = urllib.request.Request(
        "https://api.github.com/repos/%s/issues/%s/comments" % (REPO, sys.argv[1]),
        data=json.dumps({"body": body}).encode(), method="POST",
        headers={"Authorization": "Bearer " + TOK, "Accept": "application/vnd.github+json",
                 "User-Agent": "prcomment", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            print("commented:", resp.status)
            return 0
    except urllib.error.HTTPError as exc:
        print("failed:", exc.code, (exc.read() or b"").decode()[:150])
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
