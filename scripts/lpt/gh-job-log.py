#!/usr/bin/env python3
"""Read ONE GitHub Actions job's log, without touching the repo checkout.

GitHub answers /actions/jobs/<id>/logs with a 302 to signed blob storage, and urllib keeps the
Authorization header across the redirect - blob storage then answers 401 and the log looks
unreachable. Strip the header on the redirect only.

  gh-job-log.py <job-id> [--grep REGEX] [--tail N]
"""
import re
import sys
import urllib.request

REPO = "lakewoodphone/phone-and-tech-full"
CREDS = "/root/.git-credentials"


class NoAuthRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None:
            new.remove_header("Authorization")
            new.headers.pop("Authorization", None)
            new.unredirected_hdrs.pop("Authorization", None)
        return new


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    job = sys.argv[1]
    pattern = None
    tail = 40
    if "--grep" in sys.argv:
        pattern = re.compile(sys.argv[sys.argv.index("--grep") + 1])
    if "--tail" in sys.argv:
        tail = int(sys.argv[sys.argv.index("--tail") + 1])
    tok = open(CREDS, encoding="utf-8").read().strip().split(":", 2)[2].split("@", 1)[0]
    url = "https://api.github.com/repos/%s/actions/jobs/%s/logs" % (REPO, job)
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + tok, "User-Agent": "x",
                                              "Accept": "application/vnd.github+json"})
    opener = urllib.request.build_opener(NoAuthRedirect)
    text = opener.open(req, timeout=180).read().decode("utf-8", "replace")
    lines = text.splitlines()
    if pattern is not None:
        lines = [ln for ln in lines if pattern.search(ln)]
        print("matched %d line(s); last %d:" % (len(lines), tail))
    for ln in lines[-tail:]:
        print(ln[-220:])
    return 0


if __name__ == "__main__":
    sys.exit(main())
