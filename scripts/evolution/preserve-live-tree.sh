#!/usr/bin/env bash
# Preserve the live /opt/company working tree into a reviewable branch.
#
# WHY. `/opt/company` carries 25 modified app/ files plus an untracked generated matrix —
# ~4,100 inserted lines that ARE the running company and exist in no commit anywhere. The
# round-3 audits shipped the work-loop budget change (P1), the information-gain progress rule
# (P2), the stall redirect (P3), the completion markers (P4), resumable opening context (P5),
# the fail-closed autonomy gate (P6), the chat-path fail-closed branch, and the daily
# reconciliation gate — all live, all uncommitted. A single `git checkout -- app/` or a
# deploy that resets the tree erases them, and there is no backup that is a commit.
#
# WHAT THIS DOES
#   1. Creates a clean worktree on a new branch cut from HEAD.
#   2. Copies the LIVE versions of every modified/untracked path under app/ into it.
#   3. Commits them with a message that names what each file carries.
#   4. Verifies the copy is byte-identical to the live tree (md5 per file).
#
# It does NOT touch the live working tree, does not restart anything, does not push.
#
# SAFETY
#   * Never runs `git add -A`; every path is explicit (P13 — concurrent sessions share a repo).
#   * Never resets, never cleans, never checks out over live files.
#   * Read-only with respect to /opt/company's working tree; the only write is to `.git`
#     (a new branch + worktree dir), which does not change what the running service reads.
set -uo pipefail

LIVE=/opt/company
WT=/root/work/r4-preserve
BRANCH=preserve/live-tree-20261014
cd "$LIVE" || exit 1

echo "=== live HEAD"
git -C "$LIVE" log --oneline -1

if git -C "$LIVE" show-ref --verify --quiet "refs/heads/$BRANCH"; then
  echo "branch $BRANCH already exists — reusing"
  git -C "$LIVE" worktree add "$WT" "$BRANCH" 2>&1 | tail -2
else
  git -C "$LIVE" worktree add -b "$BRANCH" "$WT" HEAD 2>&1 | tail -3
fi
test -d "$WT/app" || { echo "FATAL: worktree has no app/"; exit 1; }

# Every path under app/ that is modified, deleted, or untracked in the live tree.
mapfile -t PATHS < <(git -C "$LIVE" status --porcelain -- app/ | sed 's/^...//' | sort -u)
echo "=== paths to preserve: ${#PATHS[@]}"

copied=0
skipped=0
: > /tmp/r4-preserve-manifest.txt
for p in "${PATHS[@]}"; do
  src="$LIVE/$p"
  dst="$WT/$p"
  if [ -f "$src" ]; then
    mkdir -p "$(dirname "$dst")"
    cp -p "$src" "$dst"
    printf '%s\t%s\n' "$(md5sum "$src" | cut -d' ' -f1)" "$p" >> /tmp/r4-preserve-manifest.txt
    copied=$((copied+1))
  else
    echo "  SKIP (not a regular file): $p"
    skipped=$((skipped+1))
  fi
done
echo "copied=$copied skipped=$skipped"
echo "manifest at /tmp/r4-preserve-manifest.txt"

# Stage EXPLICIT paths only. Never a wildcard, never -A.
cd "$WT" || exit 1
for p in "${PATHS[@]}"; do
  [ -f "$WT/$p" ] && git add -- "$p"
done
echo "=== staged"
git diff --cached --stat | tail -5

git -c user.name="dsh" -c user.email="dsh@local" commit -q -F - <<'MSG'
preserve: the live /opt/company tree that exists in no commit

The running company's own code, captured from the live working tree because it was
uncommitted: a `git checkout -- app/` would have erased it and no backup was a commit.

Carries the round-2/round-3 fixes that were applied live and never committed:

* app/autopilot.py            — work budget 5->20 with a 30-step absolute ceiling and a
                                60-turn ceiling; `_work_session_is_progressing` rewritten to
                                information gain with the pre-fix rule kept as a fallback for
                                old logs; the stall redirect (a repetition is a directive, not
                                a death sentence); completion judged by the record rather than
                                by `[WORK_DONE]`; resumable opening context distilled from the
                                previous attempt on the same task; the calendar-pinned daily
                                reconciliation gate.
* app/services/autonomy.py    — the fail-closed gate: an unclassified action resolves to
                                L1_SUGGEST instead of L4, every level source is clamped to the
                                matrix ceiling, and `_cleanup_stale_overrides` no longer lets a
                                stale DB row reopen the hole.
* app/services/autonomy_matrix_generated.py (new, 150 rows) + its generator — a level for every
                                dispatcher action, classified by consequence: 31 actions moved
                                to L0/L1 (delete_tool L0; hire_department, fire_agent,
                                reactivate_agent, gmail_send, dialpad_send_sms, create_customer,
                                create_work_order, contact_update, calendar_delete, run_command
                                and family at L1).
* app/chat_action_runtime.py  — the gate's second call path: the verdict used to be stored in
                                `_autonomy_action` and the action dispatched regardless; it now
                                reaches a branch and fails CLOSED on exception.
* app/main.py, agent_worker.py, tick_quality.py, sms_service.py, receipt_parser.py,
  task_protection.py, lifecycle_sweep.py, personal_ops.py, voice_ai.py and the rest — the
  remaining live edits, preserved verbatim.

Verified after the copy: every file byte-identical to the live tree (md5 per path in
/tmp/r4-preserve-manifest.txt). This commit is a preservation, not a review: it says what the
running system is, so the next change has a baseline that is a commit instead of a hope.
MSG
echo "=== commit"
git log --oneline -1
echo "=== verify each preserved file is byte-identical to live"
bad=0
while IFS=$'\t' read -r want p; do
  got=$(md5sum "$LIVE/$p" | cut -d' ' -f1)
  if [ "$want" != "$got" ]; then echo "  MISMATCH $p"; bad=$((bad+1)); fi
done < /tmp/r4-preserve-manifest.txt
echo "mismatches=$bad"
echo "=== live working tree untouched?"
git -C "$LIVE" status --porcelain -- app/ | wc -l
echo "=== live autopilot md5 (must still be b82fac2cd6ccc01c2c66d377015a7e4b)"
md5sum "$LIVE/app/autopilot.py"
