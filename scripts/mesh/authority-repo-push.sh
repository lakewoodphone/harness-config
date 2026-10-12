#!/usr/bin/env bash
# authority-repo-push.sh — keep the GitHub mirror current with the authority.
#
# WHY THIS EXISTS
#   On 2026-10-11 the company authority moved to this host (secratary-cloud).
#   The repository came with it, but the credential did not: for a day and a
#   half the authority accumulated commits that existed on exactly one NVMe,
#   because `git push` had nothing to authenticate with. Measured 2026-10-12
#   02:5xZ: `origin/master` was 006cde5a (2026-10-07) while the authority's
#   master was 15 commits ahead, and the error was
#   `fatal: could not read Username for 'https://github.com'`.
#   The credential is now at /root/.git-credentials (600 root) with
#   `credential.helper=store`; this job is what keeps it from happening again.
#
# WHAT IT WILL NOT DO
#   It never force-pushes. If origin has commits this branch does not have, it
#   refuses and exits 4, leaving both sides intact for a human. A mirror that
#   silently rewrote the authority would be worse than a stale mirror.
#
# EXIT CODES (cron-wrap records these in /root/.cron-status/runs.tsv)
#   0  up to date, or pushed
#   2  no repository at the configured path
#   3  fetch failed (network or credential)
#   4  diverged — refused on purpose, a human must reconcile
#   5  push failed
set -uo pipefail

REPO="${AUTHORITY_REPO:-/opt/company}"
BRANCH="${AUTHORITY_BRANCH:-master}"

cd "$REPO" 2>/dev/null || { echo "authority-repo-push: no repository at $REPO"; exit 2; }

if ! timeout 120 git fetch --quiet origin 2>&1; then
    echo "authority-repo-push: git fetch failed (network or credential)"
    exit 3
fi

# A missing origin/<branch> makes both rev-list counts below read as 0, which
# would report "up to date" for a branch that has never been pushed. Refuse
# instead of guessing.
if ! git rev-parse --verify --quiet "origin/$BRANCH" >/dev/null; then
    echo "authority-repo-push: origin/$BRANCH does not exist; refusing to guess what to do"
    exit 6
fi

ahead=$(git rev-list --count "origin/$BRANCH..$BRANCH" 2>/dev/null || echo 0)
behind=$(git rev-list --count "$BRANCH..origin/$BRANCH" 2>/dev/null || echo 0)
head_short=$(git rev-parse --short "$BRANCH" 2>/dev/null || echo unknown)

if [ "$ahead" = "0" ]; then
    echo "authority-repo-push: $BRANCH up to date with origin at $head_short"
    exit 0
fi

if [ "$behind" != "0" ]; then
    echo "authority-repo-push: REFUSED — origin/$BRANCH has $behind commit(s) this branch does not have, and this branch has $ahead it does not. Nothing was pushed; a human must reconcile. This job never merges and never force-pushes."
    exit 4
fi

if timeout 300 git push --quiet origin "$BRANCH" 2>&1; then
    echo "authority-repo-push: pushed $ahead commit(s); $BRANCH is now $head_short on origin"
    exit 0
fi

echo "authority-repo-push: push failed (credential or remote)"
exit 5
