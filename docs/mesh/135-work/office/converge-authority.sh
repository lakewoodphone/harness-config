# converge-authority.sh — make the authority's config_sync record STOP going red, every 15 minutes.
#
# Why this exists: harness-config tracks `journal/index/{journal.db,entries.tsv,stamp.json}`, which are
# GENERATED (rebuilt by `journal.py index`), and every `journal.py` read on this host rewrites them. So
# the checkout is dirty within a minute of every commit, and `git merge --ff-only` refuses on a dirty
# tree -- which is what puts the kernel's `config_sync` check into `attention` with "histories
# diverged", several times an hour. Measured 2026-09-28: the same flag came back within two minutes of
# being cleared twice.
#
# What this does, and does not do: it commits the generated churn, fetches, fast-forwards, and pushes.
# It never merges divergent content, never resets, and never force-pushes. If the tree cannot
# fast-forward it says so and leaves everything alone.
#
# THE REAL FIX, not done here: stop tracking `journal/index/*` (or write the stamp so it does not
# dirty the tree). That is a change to what harness-config tracks and belongs in a session that can
# verify it on both machines; this script only stops the bleeding.
#
# ---------------------------------------------------------------------------------------------
# THE 206-RUN RED STREAK, FIXED 2026-10-02 (read this before changing the target again)
# ---------------------------------------------------------------------------------------------
# This script used to hardcode `origin/master` as the thing to converge to, no matter which branch the
# authority's checkout was on. Measured 2026-10-02: the checkout has been on a work branch
# (`agent/housekeeping-wake-sources-sync` from 2026-09-29T09:45Z, `hk/176-headless-resume` from
# 2026-10-01T14:31Z) while this job compared it against `origin/master` and reported
# `[diverged] behind=121 ahead=66` on every single run -- 206 runs, 206 failures, since the first run
# was recorded in ~/.cron-status/runs.tsv. The branch is NOT a fault: `hk/176-headless-resume` was
# 0 behind / 0 ahead of ITS OWN upstream at that moment, i.e. fully published. Two different branches
# always differ; comparing them can never converge and can never be fixed by a fast-forward.
#
# So the target is now the CHECKED-OUT branch's own upstream (@{u}), and that is what "converged"
# means: this checkout is level with the ref its own `git push` publishes to. That is the honest
# definition for a checkout whose branch follows the work, and it is the same thing the kernel's
# harness pain check P195 measures (`git rev-list --count '@{u}..HEAD'`). Commits on a work branch are
# real data, so this script publishes them rather than treating them as drift.
#
# EXIT CODES
#   0  converged: upstream is fetched, we are not behind, nothing local is unpublished
#   1  FAULT: the repo is missing, a git command failed, or a push was refused -- a human should look
#   3  CONDITION, NOT FAULT: the branch cannot be reconciled automatically (real divergence, or no
#      upstream configured). This is a state that needs a decision, not a broken job, so it is
#      reported with a code distinct from 1 and the record stays readable.
# Old behaviour exited 1 for the divergence case, which is why the record could not distinguish
# "this job is broken" from "this branch needs a human" -- and why 206 identical red rows taught
# everyone to ignore it.
set -uo pipefail

REPO="${HARNESS_JOURNAL_REPO:-$HOME/harness-config}"
cd "$REPO" || exit 1   # path was $HOME, not $REPO; with `cd` failing the old `exit 2` still meant "broken"
LOG="$HOME/.harness-config-autosync/converge.log"
say() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1" >> "$LOG"; }

BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null)"
if [ -z "$BRANCH" ] || [ "$BRANCH" = "HEAD" ]; then
  say "[fault] detached HEAD -- cannot decide an upstream, not touching the tree"
  exit 1
fi

# The ref this checkout publishes to. Falls back to origin/master only when the branch genuinely has
# no upstream configured, so a branch that is merely unnamed still converges against the old target
# instead of silently doing nothing.
UPSTREAM="$(git rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null)"
if [ -z "$UPSTREAM" ]; then
  if git rev-parse --verify --quiet refs/remotes/origin/master >/dev/null; then
    UPSTREAM="origin/master"
    say "[note] $BRANCH has no upstream; falling back to origin/master"
  else
    say "[condition] $BRANCH has no upstream and there is no origin/master to fall back to"
    exit 3
  fi
fi

# 1. commit the generated churn under journal/ only
if [ -n "$(git status --porcelain -- journal | head -1)" ]; then
  git add -- journal 2>/dev/null
  git -c user.name=zabz -c user.email=zabz@lakewoodphoneandtech.com \
      commit -q -m "journal: autocommit $(git diff --cached --name-only -- journal | wc -l | tr -d ' ') path(s) (generated index churn)" 2>/dev/null
fi

# 2. fetch, then compare against the branch's OWN upstream
git fetch origin >/dev/null 2>&1 || { say "[offline] fetch failed; nothing changed"; exit 1; }
set -- $(git rev-list --left-right --count "$UPSTREAM"...HEAD)
BEHIND="${1:-0}"; AHEAD="${2:-0}"
if [ "$AHEAD" != "0" ] && [ "$BEHIND" != "0" ]; then
  say "[condition] $BRANCH diverged from $UPSTREAM: behind=$BEHIND ahead=$AHEAD -- not merging automatically, a human should look"
  exit 3
fi

# 3. behind only: fast-forward onto the upstream. Refuse (do not merge) if the tree will not take it.
if [ "$BEHIND" != "0" ]; then
  git merge --ff-only "$UPSTREAM" >/dev/null 2>&1 || {
    say "[condition] $BRANCH is behind=$BEHIND $UPSTREAM but the tree will not fast-forward"
    exit 3
  }
fi

# 4. publish anything local, to this branch's own upstream
if [ "$AHEAD" != "0" ]; then
  if ! git push origin HEAD >/dev/null 2>&1; then
    say "[fault] behind=$BEHIND ahead=$AHEAD but the push to $UPSTREAM was refused"
    exit 1
  fi
fi

# 5. report the state that is actually true now, measured rather than assumed
set -- $(git rev-list --left-right --count "$UPSTREAM"...HEAD)
FINAL_BEHIND="${1:-0}"; FINAL_AHEAD="${2:-0}"
if [ "$FINAL_BEHIND" != "0" ] || [ "$FINAL_AHEAD" != "0" ]; then
  say "[condition] $BRANCH still behind=$FINAL_BEHIND ahead=$FINAL_AHEAD of $UPSTREAM after the attempt"
  exit 3
fi
say "[converged] $BRANCH level with $UPSTREAM (behind=0 ahead=0)"
exit 0
