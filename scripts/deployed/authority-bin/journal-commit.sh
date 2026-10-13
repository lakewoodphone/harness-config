#!/usr/bin/env bash
# journal-commit.sh — make journal entries written ON THE AUTHORITY into COMMITS, and PUBLISH them.
#
# WHY THIS EXISTS (measured 2026-09-22, on the office box)
# --------------------------------------------------------
# `journal.py append` writes locally only and never moves a ref, by design (the 2026-09-17
# incident). `scripts/autosync.sh` never commits, merges, rebases or resets — also by design.
# Between the two of them, entries written on the authority sat as uncommitted files that autosync
# could not see (it counts commits, and its dirty count excludes untracked files), while autosync
# watched a *different* checkout that was always clean. Result: the journal on the authority
# reached 5 ahead / 102 behind origin in three days and **nothing reported it**. Reconciling that
# cost a merge with 21 id collisions.
#
# Measured on the office box over the life of the job: 1003 runs, **284 non-zero (28 %)** — the
# highest failure rate of any job that was not plainly dead. The cause was a git-index collision
# with `converge-authority.sh` committing journal/ in the same repo on the same */15 minute.
#
# PORTED TO secratary-cloud, 2026-10-11. WHAT CHANGED, AND WHY
# -----------------------------------------------------------
# 1. **The checkout moved.** The canonical journal checkout on this estate is
#    `/root/code/harness-config` on the authority — not `~/code/harness-config` on a laptop that
#    is shut at night. `JOURNAL_REPO` overrides it.
# 2. **It PUBLISHES, and it verifies that it did.** The office job's second half was `autosync.sh`,
#    which published to a bare repo living on the office box itself — a journal commit that never
#    leaves the machine is not a backup. This job pushes to a remote that is a DIFFERENT machine
#    (`JOURNAL_REMOTE_URL`, default the VPS at /srv/git/harness-config.git) and reads the remote's
#    own HEAD back afterwards, so "pushed" is a measurement and not an assumption.
# 3. **The collision dance is gone, not guessed at.** There is no second committer on the cloud
#    authority, so there is no race to lose. The office version needed a 15-second lock-retry loop;
#    keeping it here would be preserving a workaround for a condition that no longer exists.
# 4. **Nothing is forced, ever.** No `--force`, no `reset`, no `rebase`, no stash, no push to a
#    ref it did not create. A rejected push is reported, not overpowered: the entries stay in the
#    tree and the next tick tries again.
#
# It commits changes under `journal/` ONLY. It does not touch any other path, any other branch, or
# any other ref. It exits 0 when there was nothing to do.
set -uo pipefail

REPO="${JOURNAL_REPO:-/root/code/harness-config}"
# The remote DEFAULTS TO THE VAULT (`vault`), a bare repo on a different provider, because the
# `origin` this box was cloned from is a git bundle on its OWN disk: a commit that never leaves the
# machine is not a backup, and reading "committed" as "safe" is how that goes unnoticed. The bundle
# remote is kept as `origin` for history, but nothing is published to it.
REMOTE="${JOURNAL_REMOTE:-vault}"
BRANCH="${JOURNAL_BRANCH:-main}"
STATE="${JOURNAL_STATE:-/root/.harness-config-autosync}"
LOG="$STATE/journal-commit.log"
mkdir -p "$STATE" 2>/dev/null
say() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1" | tee -a "$LOG"; }

cd "$REPO" 2>/dev/null || { say "[cannot-run] not a directory: $REPO"; exit 2; }
[ -d "$REPO/.git" ] || { say "[cannot-run] not a git repo: $REPO"; exit 2; }

# Never fight another git operation: a session mid-merge, mid-rebase or mid-write must win.
for f in MERGE_HEAD REBASE_HEAD CHERRY_PICK_HEAD index.lock; do
  if [ -e "$REPO/.git/$f" ]; then say "[skip] $f present - a git operation is in progress"; exit 0; fi
done
[ -d "$REPO/.git/rebase-merge" ] || [ -d "$REPO/.git/rebase-apply" ] && { say "[skip] rebase in progress"; exit 0; }

if [ "${JOURNAL_SELFTEST:-0}" = "1" ]; then
  say "[selftest] journal-commit reachable: repo=$REPO remote=$(git remote get-url "$REMOTE" 2>/dev/null || echo NONE) branch=$BRANCH"
fi

# A LOCAL COMMIT THAT WAS NEVER PUSHED IS STILL A COMMIT THAT LIVES ON ONE MACHINE. Measured
# 2026-10-11: the first run after the remote was wired committed and then failed its push; the next
# run found nothing to commit and exited 0, leaving the branch ahead of the remote forever. So before
# deciding there is nothing to do, compare HEAD with the remote and publish if the remote is behind.
REMOTE_HEAD_NOW="$(timeout 30 git ls-remote "$REMOTE" "refs/heads/$BRANCH" 2>/dev/null | awk '{print $1}')"
LOCAL_HEAD_NOW="$(git rev-parse HEAD)"
if [ -n "$REMOTE_HEAD_NOW" ] && [ "$REMOTE_HEAD_NOW" != "$LOCAL_HEAD_NOW" ]; then
  say "[ahead] the remote is behind (remote ${REMOTE_HEAD_NOW:0:7}, local ${LOCAL_HEAD_NOW:0:7}) - pushing"
  if git push -q "$REMOTE" "HEAD:$BRANCH" >"$STATE/last-push.out" 2>&1; then
    say "[pushed] $(git rev-parse --short HEAD) published to $(git remote get-url "$REMOTE") $BRANCH"
  else
    say "[failed] push to $REMOTE $BRANCH -- $(head -c 300 "$STATE/last-push.out" | tr '\n' ' ')"
  fi
fi
if [ -z "$(git status --porcelain -- journal | head -1)" ]; then
  exit 0
fi

if ! git add -- journal 2>"$STATE/last-add.err"; then
  say "[failed] git add journal/ -- $(head -c 200 "$STATE/last-add.err" | tr '\n' ' ')"
  exit 1
fi
N="$(git diff --cached --name-only -- journal | wc -l | tr -d ' ')"
[ "$N" = "0" ] && exit 0

if ! git -c user.name=zabz -c user.email=zabz@lakewoodphoneandtech.com \
     commit -q -m "journal: autocommit $N path(s) on $BRANCH from $(hostname) at $(date -u +%FT%TZ)"; then
  say "[failed] commit refused ($N path(s) staged, left staged for a human)"
  exit 1
fi
HEAD_LOCAL="$(git rev-parse --short HEAD)"
say "[commit] $N path(s) on $BRANCH at $HEAD_LOCAL"

# ── PUBLISH, and prove it left the building ───────────────────────────────────────────────────
# The remote is read back over the network. If it cannot be reached, that is a FAILURE reported
# with its reason -- not a green run that shipped nothing, which is the defect this estate has
# paid for twice (`PersonalSecretary-PushVSCodeChats`: 21 days of `LastTaskResult=0` while the
# archive stood still).
if ! git push -q "$REMOTE" "HEAD:$BRANCH" >"$STATE/last-push.out" 2>&1; then
  say "[failed] push to $REMOTE $BRANCH -- $(head -c 300 "$STATE/last-push.out" | tr '\n' ' ')"
  exit 1
fi
REMOTE_URL="$(git remote get-url "$REMOTE" 2>/dev/null)"
if [ -n "$REMOTE_URL" ]; then
  HEAD_REMOTE="$(git ls-remote "$REMOTE" "refs/heads/$BRANCH" 2>/dev/null | awk '{print substr($1,1,7)}')"
  if [ "$HEAD_REMOTE" = "$HEAD_LOCAL" ]; then
    say "[pushed] $HEAD_LOCAL published to $REMOTE_URL $BRANCH (remote HEAD read back and matches)"
  else
    say "[failed] push reported success but $REMOTE $BRANCH reads '${HEAD_REMOTE:-<nothing>}', not $HEAD_LOCAL"
    exit 1
  fi
fi
exit 0
